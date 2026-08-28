#pragma once

#include <cstdint>
#include <vector>

namespace vector_engine {

std::vector<double> signed_distance_field(const std::vector<std::uint8_t>& mask,
                                          int width, int height);

}  // namespace vector_engine
