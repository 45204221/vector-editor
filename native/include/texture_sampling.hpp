#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace vector_engine {

struct TextureLevel {
    int width{};
    int height{};
    std::vector<std::uint8_t> rgba;
};

struct TextureFootprint {
    double major{};
    double minor{};
    double ratio{1.0};
    double isotropic_lod{};
    double anisotropic_lod{};
    double direction_u{1.0};
    double direction_v{};
    int taps{1};
};

std::vector<TextureLevel> generate_mipmaps(
    const std::vector<std::uint8_t>& rgba, int width, int height);

std::array<std::uint8_t, 4> sample_mipmaps(
    const std::vector<TextureLevel>& levels, double u, double v, double lod,
    const std::string& filter, bool repeat);

TextureFootprint texture_footprint(
    int width, int height, double dudx, double dvdx, double dudy,
    double dvdy, int max_taps);

std::pair<std::array<std::uint8_t, 4>, TextureFootprint> sample_anisotropic(
    const std::vector<TextureLevel>& levels, double u, double v,
    double dudx, double dvdx, double dudy, double dvdy, int max_taps,
    bool repeat);

}  // namespace vector_engine
