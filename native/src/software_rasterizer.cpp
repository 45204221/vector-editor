#include "software_rasterizer.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace vector_engine {
namespace {

constexpr double kEpsilon = 1e-10;

struct ScreenVertex {
    double x{}, y{}, depth{}, inv_w{}, r{}, g{}, b{};
};

double edge(const ScreenVertex& first, const ScreenVertex& second,
            double x, double y) {
    return (x - first.x) * (second.y - first.y) -
           (y - first.y) * (second.x - first.x);
}

bool is_top_left(const ScreenVertex& first, const ScreenVertex& second) {
    const double dx = second.x - first.x;
    const double dy = second.y - first.y;
    return dy < 0.0 || (std::abs(dy) <= kEpsilon && dx > 0.0);
}

bool accepts_edge(double value, bool top_left) {
    return value > kEpsilon || (value >= -kEpsilon && top_left);
}

std::uint8_t byte(double value) {
    return static_cast<std::uint8_t>(std::lround(
        std::clamp(value, 0.0, 1.0) * 255.0));
}

void write_rgba(std::vector<std::uint8_t>& output, std::size_t pixel,
                double r, double g, double b) {
    const std::size_t offset = pixel * 4;
    output[offset] = byte(r); output[offset + 1] = byte(g);
    output[offset + 2] = byte(b); output[offset + 3] = 255;
}

RasterVertex interpolate(const RasterVertex& first,
                         const RasterVertex& second, double amount) {
    RasterVertex output;
    const auto mix = [amount](double a, double b) {
        return a + (b - a) * amount;
    };
    output.clip_x = mix(first.clip_x, second.clip_x);
    output.clip_y = mix(first.clip_y, second.clip_y);
    output.clip_z = mix(first.clip_z, second.clip_z);
    output.clip_w = mix(first.clip_w, second.clip_w);
    output.r = mix(first.r, second.r);
    output.g = mix(first.g, second.g);
    output.b = mix(first.b, second.b);
    return output;
}

double plane_distance(const RasterVertex& vertex, int plane) {
    switch (plane) {
        case 0: return vertex.clip_x + vertex.clip_w;
        case 1: return vertex.clip_w - vertex.clip_x;
        case 2: return vertex.clip_y + vertex.clip_w;
        case 3: return vertex.clip_w - vertex.clip_y;
        case 4: return vertex.clip_z + vertex.clip_w;
        default: return vertex.clip_w - vertex.clip_z;
    }
}

std::vector<RasterVertex> clip_triangle(const RasterVertex* triangle) {
    std::vector<RasterVertex> polygon(triangle, triangle + 3);
    for (int plane = 0; plane < 6 && !polygon.empty(); ++plane) {
        std::vector<RasterVertex> output;
        RasterVertex previous = polygon.back();
        double previous_distance = plane_distance(previous, plane);
        bool previous_inside = previous_distance >= 0.0;
        for (const auto& current : polygon) {
            const double current_distance = plane_distance(current, plane);
            const bool current_inside = current_distance >= 0.0;
            if (current_inside != previous_inside) {
                const double denominator = previous_distance - current_distance;
                const double amount = std::abs(denominator) <= 1e-15
                    ? 0.0 : previous_distance / denominator;
                output.push_back(interpolate(previous, current, amount));
            }
            if (current_inside) output.push_back(current);
            previous = current;
            previous_distance = current_distance;
            previous_inside = current_inside;
        }
        polygon.swap(output);
    }
    return polygon;
}

}  // namespace

RasterResult software_rasterize(const std::vector<RasterVertex>& vertices,
                                int width, int height,
                                bool perspective_correct,
                                bool cull_back_faces,
                                bool clip_volume,
                                int sample_count) {
    if (width <= 0 || height <= 0 || width > 512 || height > 512) {
        throw std::invalid_argument("raster dimensions must be between 1 and 512");
    }
    if (vertices.size() % 3 != 0 || vertices.size() > 300000) {
        throw std::invalid_argument("vertices must be a bounded triangle list");
    }
    if (sample_count != 1 && sample_count != 4) {
        throw std::invalid_argument("sample_count must be 1 or 4");
    }
    const auto started = std::chrono::steady_clock::now();
    RasterResult result;
    result.width = width; result.height = height;
    result.input_triangles = vertices.size() / 3;
    result.sample_count = sample_count;
    const std::size_t pixels = static_cast<std::size_t>(width) *
                               static_cast<std::size_t>(height);
    const std::size_t samples = pixels * static_cast<std::size_t>(sample_count);
    const std::array<double, 3> background{0.055, 0.075, 0.105};
    std::vector<std::array<double, 3>> sample_color(samples, background);
    std::vector<std::array<double, 3>> sample_bary(samples, background);
    std::vector<std::array<double, 3>> sample_depth_image(samples, background);
    std::vector<float> depth_buffer(samples, 1.0F);
    std::vector<std::uint32_t> sample_primitive(samples, 0);
    const std::array<std::array<double, 2>, 4> positions{{
        {{0.375, 0.125}}, {{0.875, 0.375}},
        {{0.125, 0.625}}, {{0.625, 0.875}}
    }};

    auto rasterize_triangle = [&](const RasterVertex* input,
                                  std::size_t primitive) {
        ScreenVertex screen[3];
        for (int index = 0; index < 3; ++index) {
            if (!std::isfinite(input[index].clip_w) ||
                    input[index].clip_w <= 1e-9) return;
            const double inv_w = 1.0 / input[index].clip_w;
            const double ndc_x = input[index].clip_x * inv_w;
            const double ndc_y = input[index].clip_y * inv_w;
            const double ndc_z = input[index].clip_z * inv_w;
            screen[index] = {(ndc_x * 0.5 + 0.5) * (width - 1),
                             (1.0 - (ndc_y * 0.5 + 0.5)) * (height - 1),
                             ndc_z * 0.5 + 0.5, inv_w,
                             input[index].r, input[index].g, input[index].b};
        }
        double area = edge(screen[0], screen[1], screen[2].x, screen[2].y);
        if (std::abs(area) <= 1e-12) return;
        if (cull_back_faces && area <= 0.0) return;
        if (area < 0.0) {
            std::swap(screen[1], screen[2]);
            area = -area;
        }
        ++result.rasterized_triangles;
        const int min_x = std::max(0, static_cast<int>(std::floor(
            std::min({screen[0].x, screen[1].x, screen[2].x}))));
        const int max_x = std::min(width - 1, static_cast<int>(std::ceil(
            std::max({screen[0].x, screen[1].x, screen[2].x}))));
        const int min_y = std::max(0, static_cast<int>(std::floor(
            std::min({screen[0].y, screen[1].y, screen[2].y}))));
        const int max_y = std::min(height - 1, static_cast<int>(std::ceil(
            std::max({screen[0].y, screen[1].y, screen[2].y}))));
        const bool top_left[3] = {
            is_top_left(screen[1], screen[2]),
            is_top_left(screen[2], screen[0]),
            is_top_left(screen[0], screen[1])
        };
        for (int y = min_y; y <= max_y; ++y) {
            for (int x = min_x; x <= max_x; ++x) {
                for (int sample_index = 0; sample_index < sample_count; ++sample_index) {
                    const double px = x + (sample_count == 1 ? 0.5 : positions[sample_index][0]);
                    const double py = y + (sample_count == 1 ? 0.5 : positions[sample_index][1]);
                    const double edge_values[3] = {
                        edge(screen[1], screen[2], px, py),
                        edge(screen[2], screen[0], px, py),
                        edge(screen[0], screen[1], px, py)
                    };
                    if (!accepts_edge(edge_values[0], top_left[0]) ||
                        !accepts_edge(edge_values[1], top_left[1]) ||
                        !accepts_edge(edge_values[2], top_left[2])) continue;
                    ++result.covered_fragments;
                    const double weights[3] = {
                        edge_values[0] / area, edge_values[1] / area,
                        edge_values[2] / area
                    };
                    const double z = weights[0] * screen[0].depth +
                                     weights[1] * screen[1].depth +
                                     weights[2] * screen[2].depth;
                    const std::size_t pixel = static_cast<std::size_t>(y) * width + x;
                    const std::size_t sample = pixel * sample_count + sample_index;
                    if (z < 0.0 || z > 1.0 || z >= depth_buffer[sample]) continue;
                    double attributes[3] = {weights[0], weights[1], weights[2]};
                    if (perspective_correct) {
                        const double denominator = weights[0] * screen[0].inv_w +
                                                   weights[1] * screen[1].inv_w +
                                                   weights[2] * screen[2].inv_w;
                        if (std::abs(denominator) <= 1e-12) continue;
                        for (int index = 0; index < 3; ++index) {
                            attributes[index] = weights[index] * screen[index].inv_w /
                                                denominator;
                        }
                    }
                    depth_buffer[sample] = static_cast<float>(z);
                    ++result.depth_passed_fragments;
                    sample_color[sample] = {
                        attributes[0] * screen[0].r + attributes[1] * screen[1].r + attributes[2] * screen[2].r,
                        attributes[0] * screen[0].g + attributes[1] * screen[1].g + attributes[2] * screen[2].g,
                        attributes[0] * screen[0].b + attributes[1] * screen[1].b + attributes[2] * screen[2].b
                    };
                    sample_bary[sample] = {attributes[0], attributes[1], attributes[2]};
                    sample_depth_image[sample] = {z, z, z};
                    sample_primitive[sample] = static_cast<std::uint32_t>(primitive);
                }
            }
        }
    };

    for (std::size_t start = 0; start < vertices.size(); start += 3) {
        const std::size_t primitive = start / 3 + 1;
        if (clip_volume) {
            const auto polygon = clip_triangle(vertices.data() + start);
            if (polygon.size() < 3) continue;
            result.clipped_triangles += polygon.size() - 2;
            for (std::size_t index = 1; index + 1 < polygon.size(); ++index) {
                const RasterVertex triangle[3] = {polygon[0], polygon[index],
                                                  polygon[index + 1]};
                rasterize_triangle(triangle, primitive);
            }
        } else {
            ++result.clipped_triangles;
            rasterize_triangle(vertices.data() + start, primitive);
        }
    }

    result.color.assign(pixels * 4, 255);
    result.barycentric.assign(pixels * 4, 255);
    result.depth.assign(pixels * 4, 255);
    result.primitive_id.assign(pixels * 4, 0);
    for (std::size_t pixel = 0; pixel < pixels; ++pixel) {
        double color[3]{}; double bary[3]{}; double depth[3]{};
        std::uint32_t primitive = 0;
        float nearest = std::numeric_limits<float>::infinity();
        for (int index = 0; index < sample_count; ++index) {
            const std::size_t sample = pixel * sample_count + index;
            for (int channel = 0; channel < 3; ++channel) {
                color[channel] += sample_color[sample][channel];
                bary[channel] += sample_bary[sample][channel];
            }
            for (int channel = 0; channel < 3; ++channel) {
                depth[channel] += sample_depth_image[sample][channel];
            }
            if (sample_primitive[sample] != 0 && depth_buffer[sample] < nearest) {
                nearest = depth_buffer[sample];
                primitive = sample_primitive[sample];
            }
        }
        const double divisor = static_cast<double>(sample_count);
        write_rgba(result.color, pixel, color[0] / divisor,
                   color[1] / divisor, color[2] / divisor);
        write_rgba(result.barycentric, pixel, bary[0] / divisor,
                   bary[1] / divisor, bary[2] / divisor);
        write_rgba(result.depth, pixel, depth[0] / divisor,
                   depth[1] / divisor, depth[2] / divisor);
        const std::size_t offset = pixel * 4;
        result.primitive_id[offset] = static_cast<std::uint8_t>(primitive & 0xFF);
        result.primitive_id[offset + 1] = static_cast<std::uint8_t>((primitive >> 8) & 0xFF);
        result.primitive_id[offset + 2] = static_cast<std::uint8_t>((primitive >> 16) & 0xFF);
        result.primitive_id[offset + 3] = 255;
        if (primitive != 0) ++result.resolved_covered_pixels;
    }
    result.elapsed_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - started).count();
    return result;
}

}  // namespace vector_engine
