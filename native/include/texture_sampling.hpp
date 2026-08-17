#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace vector_engine {

struct TextureLevel {
    int width{};
    int height{};
    std::vector<std::uint8_t> rgba;
};

std::vector<TextureLevel> generate_mipmaps(
    const std::vector<std::uint8_t>& rgba, int width, int height);

std::array<std::uint8_t, 4> sample_mipmaps(
    const std::vector<TextureLevel>& levels, double u, double v, double lod,
    const std::string& filter, bool repeat);

}  // namespace vector_engine
