#pragma once

#include <array>
#include <string>

namespace vector_engine {

std::array<double, 3> tone_map_rgb(
    const std::array<double, 3>& rgb, double exposure,
    const std::string& tone_mapper, double gamma = 2.2);

}  // namespace vector_engine
