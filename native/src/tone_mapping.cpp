#include "tone_mapping.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace vector_engine {

std::array<double, 3> tone_map_rgb(
        const std::array<double, 3>& rgb, double exposure,
        const std::string& tone_mapper, double gamma) {
    if (tone_mapper != "linear" && tone_mapper != "reinhard" &&
            tone_mapper != "aces") {
        throw std::invalid_argument("unsupported tone mapper");
    }
    if (!std::isfinite(exposure) || exposure < 0.0) {
        throw std::invalid_argument("exposure must be finite and non-negative");
    }
    if (!std::isfinite(gamma) || gamma <= 0.0) {
        throw std::invalid_argument("gamma must be finite and positive");
    }
    std::array<double, 3> output{};
    const double inverse_gamma = 1.0 / gamma;
    for (int channel = 0; channel < 3; ++channel) {
        if (!std::isfinite(rgb[channel]) || rgb[channel] < 0.0) {
            throw std::invalid_argument("HDR color channels must be finite and non-negative");
        }
        const double value = rgb[channel] * exposure;
        double mapped = 0.0;
        if (tone_mapper == "linear") {
            mapped = std::min(1.0, value);
        } else if (tone_mapper == "reinhard") {
            mapped = value / (1.0 + value);
        } else {
            mapped = std::clamp(
                (value * (2.51 * value + 0.03)) /
                (value * (2.43 * value + 0.59) + 0.14), 0.0, 1.0);
        }
        output[channel] = std::pow(mapped, inverse_gamma);
    }
    return output;
}

std::array<double, 3> bloom_soft_threshold(
        const std::array<double, 3>& rgb, double threshold, double knee) {
    if (!std::isfinite(threshold) || threshold < 0.0) {
        throw std::invalid_argument("threshold must be finite and non-negative");
    }
    if (!std::isfinite(knee) || knee < 0.0 || knee > 1.0) {
        throw std::invalid_argument("knee must be finite and between 0 and 1");
    }
    for (double value : rgb) {
        if (!std::isfinite(value) || value < 0.0) {
            throw std::invalid_argument("HDR color channels must be finite and non-negative");
        }
    }
    const double brightness = std::max({rgb[0], rgb[1], rgb[2]});
    const double soft_width = std::max(1e-6, threshold * knee);
    double soft = std::clamp(
        brightness - threshold + soft_width, 0.0, 2.0 * soft_width);
    soft = soft * soft / (4.0 * soft_width + 1e-6);
    const double contribution = std::max(soft, brightness - threshold) /
        std::max(brightness, 1e-6);
    return {rgb[0] * contribution, rgb[1] * contribution,
            rgb[2] * contribution};
}

double auto_exposure_from_luminance(
        const std::vector<double>& luminances, int bins,
        double min_ev, double max_ev, double low_percentile,
        double high_percentile, double middle_grey,
        double compensation_ev) {
    if (bins < 2 || bins > 256 || !(min_ev < max_ev) ||
            low_percentile < 0.0 || low_percentile >= high_percentile ||
            high_percentile > 1.0 || !std::isfinite(middle_grey) ||
            middle_grey <= 0.0 || !std::isfinite(compensation_ev)) {
        throw std::invalid_argument("invalid auto exposure parameters");
    }
    std::vector<int> histogram(static_cast<std::size_t>(bins), 0);
    for (double value : luminances) {
        if (!std::isfinite(value) || value < 0.0) {
            throw std::invalid_argument("luminance must be finite and non-negative");
        }
        const double ev = std::log2(std::max(value, std::exp2(min_ev)));
        const double normalized = std::clamp(
            (ev - min_ev) / (max_ev - min_ev), 0.0, 1.0);
        const int index = std::min(bins - 1,
            static_cast<int>(normalized * static_cast<double>(bins)));
        ++histogram[static_cast<std::size_t>(index)];
    }
    const int total = static_cast<int>(luminances.size());
    if (total == 0) return 1.0;
    const double low_count = total * low_percentile;
    const double high_count = total * high_percentile;
    const double width = (max_ev - min_ev) / bins;
    double cumulative = 0.0, weighted_ev = 0.0, selected = 0.0;
    for (int index = 0; index < bins; ++index) {
        const double start = cumulative;
        const double end = cumulative + histogram[static_cast<std::size_t>(index)];
        const double included = std::max(
            0.0, std::min(end, high_count) - std::max(start, low_count));
        if (included > 0.0) {
            weighted_ev += (min_ev + (index + 0.5) * width) * included;
            selected += included;
        }
        cumulative = end;
    }
    const double average_ev = selected > 0.0 ? weighted_ev / selected : 0.0;
    const double target = middle_grey * std::exp2(compensation_ev) /
        std::max(std::exp2(average_ev), 1e-6);
    return std::clamp(target, 0.05, 8.0);
}

}  // namespace vector_engine
