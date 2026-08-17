#include "texture_sampling.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace vector_engine {
namespace {

int coordinate(int value, int size, bool repeat) {
    if (!repeat) return std::clamp(value, 0, size - 1);
    value %= size;
    return value < 0 ? value + size : value;
}

std::array<double, 4> texel(const TextureLevel& level, int x, int y,
                            bool repeat) {
    x = coordinate(x, level.width, repeat);
    y = coordinate(y, level.height, repeat);
    const std::size_t offset = (static_cast<std::size_t>(y) * level.width + x) * 4;
    return {static_cast<double>(level.rgba[offset]),
            static_cast<double>(level.rgba[offset + 1]),
            static_cast<double>(level.rgba[offset + 2]),
            static_cast<double>(level.rgba[offset + 3])};
}

std::array<double, 4> sample_level(const TextureLevel& level, double u,
                                   double v, bool linear, bool repeat) {
    if (!std::isfinite(u) || !std::isfinite(v)) {
        throw std::invalid_argument("texture coordinates must be finite");
    }
    const double x = u * level.width - 0.5;
    const double y = v * level.height - 0.5;
    if (!linear) {
        return texel(level, static_cast<int>(std::floor(x + 0.5)),
                     static_cast<int>(std::floor(y + 0.5)), repeat);
    }
    const int x0 = static_cast<int>(std::floor(x));
    const int y0 = static_cast<int>(std::floor(y));
    const double tx = x - x0, ty = y - y0;
    const auto c00 = texel(level, x0, y0, repeat);
    const auto c10 = texel(level, x0 + 1, y0, repeat);
    const auto c01 = texel(level, x0, y0 + 1, repeat);
    const auto c11 = texel(level, x0 + 1, y0 + 1, repeat);
    std::array<double, 4> output{};
    for (int channel = 0; channel < 4; ++channel) {
        const double top = c00[channel] + (c10[channel] - c00[channel]) * tx;
        const double bottom = c01[channel] + (c11[channel] - c01[channel]) * tx;
        output[channel] = top + (bottom - top) * ty;
    }
    return output;
}

std::array<std::uint8_t, 4> bytes(const std::array<double, 4>& values) {
    std::array<std::uint8_t, 4> output{};
    for (int channel = 0; channel < 4; ++channel) {
        output[channel] = static_cast<std::uint8_t>(std::clamp(
            static_cast<int>(std::floor(values[channel] + 0.5)), 0, 255));
    }
    return output;
}

}  // namespace

std::vector<TextureLevel> generate_mipmaps(
        const std::vector<std::uint8_t>& rgba, int width, int height) {
    if (width <= 0 || height <= 0 || width > 2048 || height > 2048) {
        throw std::invalid_argument("texture dimensions must be between 1 and 2048");
    }
    const std::size_t expected = static_cast<std::size_t>(width) * height * 4;
    if (rgba.size() != expected) {
        throw std::invalid_argument("RGBA8 buffer size does not match dimensions");
    }
    std::vector<TextureLevel> levels{{width, height, rgba}};
    while (width > 1 || height > 1) {
        const auto& source = levels.back();
        const int next_width = std::max(1, (width + 1) / 2);
        const int next_height = std::max(1, (height + 1) / 2);
        TextureLevel next{next_width, next_height,
                          std::vector<std::uint8_t>(
                              static_cast<std::size_t>(next_width) * next_height * 4)};
        for (int y = 0; y < next_height; ++y) {
            for (int x = 0; x < next_width; ++x) {
                for (int channel = 0; channel < 4; ++channel) {
                    int total = 0, count = 0;
                    for (int offset_y = 0; offset_y < 2; ++offset_y) {
                        const int source_y = std::min(height - 1, y * 2 + offset_y);
                        for (int offset_x = 0; offset_x < 2; ++offset_x) {
                            const int source_x = std::min(width - 1, x * 2 + offset_x);
                            total += source.rgba[(static_cast<std::size_t>(source_y) *
                                width + source_x) * 4 + channel];
                            ++count;
                        }
                    }
                    next.rgba[(static_cast<std::size_t>(y) * next_width + x) * 4 +
                              channel] = static_cast<std::uint8_t>((total + count / 2) / count);
                }
            }
        }
        levels.push_back(std::move(next));
        width = next_width; height = next_height;
    }
    return levels;
}

std::array<std::uint8_t, 4> sample_mipmaps(
        const std::vector<TextureLevel>& levels, double u, double v, double lod,
        const std::string& filter, bool repeat) {
    if (levels.empty()) throw std::invalid_argument("mip chain cannot be empty");
    if (!std::isfinite(lod)) throw std::invalid_argument("LOD must be finite");
    if (filter != "nearest" && filter != "bilinear" && filter != "trilinear") {
        throw std::invalid_argument("filter must be nearest, bilinear or trilinear");
    }
    const double maximum = static_cast<double>(levels.size() - 1);
    lod = std::clamp(lod, 0.0, maximum);
    if (filter != "trilinear") {
        const int level = static_cast<int>(std::floor(lod + 0.5));
        return bytes(sample_level(levels[static_cast<std::size_t>(level)], u, v,
                                  filter == "bilinear", repeat));
    }
    const int first = static_cast<int>(std::floor(lod));
    const int second = std::min(first + 1, static_cast<int>(levels.size() - 1));
    const double blend = lod - first;
    const auto low = sample_level(levels[static_cast<std::size_t>(first)], u, v,
                                  true, repeat);
    const auto high = sample_level(levels[static_cast<std::size_t>(second)], u, v,
                                   true, repeat);
    std::array<double, 4> mixed{};
    for (int channel = 0; channel < 4; ++channel) {
        mixed[channel] = low[channel] + (high[channel] - low[channel]) * blend;
    }
    return bytes(mixed);
}

}  // namespace vector_engine
