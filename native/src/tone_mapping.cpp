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

}  // namespace vector_engine
