#pragma once

#include <array>
#include <string>
#include <vector>

namespace vector_engine {

std::array<double, 3> tone_map_rgb(
    const std::array<double, 3>& rgb, double exposure,
    const std::string& tone_mapper, double gamma = 2.2);

std::array<double, 3> bloom_soft_threshold(
    const std::array<double, 3>& rgb, double threshold, double knee);

double auto_exposure_from_luminance(
    const std::vector<double>& luminances, int bins = 64,
    double min_ev = -12.0, double max_ev = 4.0,
    double low_percentile = 0.02, double high_percentile = 0.98,
    double middle_grey = 0.18, double compensation_ev = 0.0);

}  // namespace vector_engine
