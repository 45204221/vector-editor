#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace vector_engine {

struct RasterVertex {
    double clip_x{};
    double clip_y{};
    double clip_z{};
    double clip_w{1.0};
    double r{};
    double g{};
    double b{};
};

struct RasterResult {
    int width{};
    int height{};
    std::vector<std::uint8_t> color;
    std::vector<std::uint8_t> barycentric;
    std::vector<std::uint8_t> depth;
    std::vector<std::uint8_t> primitive_id;
    std::size_t input_triangles{};
    std::size_t clipped_triangles{};
    std::size_t rasterized_triangles{};
    std::size_t covered_fragments{};
    std::size_t depth_passed_fragments{};
    std::size_t resolved_covered_pixels{};
    int sample_count{1};
    double elapsed_ms{};
};

RasterResult software_rasterize(const std::vector<RasterVertex>& vertices,
                                int width, int height,
                                bool perspective_correct,
                                bool cull_back_faces,
                                bool clip_volume = true,
                                int sample_count = 1);

}  // namespace vector_engine
