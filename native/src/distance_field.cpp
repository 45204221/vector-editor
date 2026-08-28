#include "distance_field.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace vector_engine {
namespace {
constexpr double kInf = 1.0e20;

std::vector<double> edt_1d(const std::vector<double>& input) {
    const int count = static_cast<int>(input.size());
    std::vector<int> finite;
    for (int index = 0; index < count; ++index)
        if (input[static_cast<std::size_t>(index)] < kInf) finite.push_back(index);
    if (finite.empty()) return std::vector<double>(input.size(), kInf);
    std::vector<int> sites(input.size());
    std::vector<double> boundaries(input.size() + 1);
    int k = 0;
    sites[0] = finite[0]; boundaries[0] = -kInf; boundaries[1] = kInf;
    for (std::size_t index = 1; index < finite.size(); ++index) {
        const int q = finite[index];
        double crossing = 0.0;
        while (true) {
            const int p = sites[static_cast<std::size_t>(k)];
            crossing = ((input[q] + q * q) - (input[p] + p * p)) /
                       (2.0 * (q - p));
            if (crossing > boundaries[static_cast<std::size_t>(k)] || k == 0) break;
            --k;
        }
        if (crossing <= boundaries[static_cast<std::size_t>(k)]) k = 0;
        else ++k;
        sites[static_cast<std::size_t>(k)] = q;
        boundaries[static_cast<std::size_t>(k)] = crossing;
        boundaries[static_cast<std::size_t>(k + 1)] = kInf;
    }
    std::vector<double> result(input.size());
    k = 0;
    for (int q = 0; q < count; ++q) {
        while (boundaries[static_cast<std::size_t>(k + 1)] < q) ++k;
        const double delta = q - sites[static_cast<std::size_t>(k)];
        result[static_cast<std::size_t>(q)] = delta * delta +
            input[static_cast<std::size_t>(sites[static_cast<std::size_t>(k)])];
    }
    return result;
}

std::vector<double> distance_to(const std::vector<std::uint8_t>& mask,
                                int width, int height, bool feature_value) {
    std::vector<std::vector<double>> rows(static_cast<std::size_t>(height));
    for (int y = 0; y < height; ++y) {
        std::vector<double> row(static_cast<std::size_t>(width), kInf);
        for (int x = 0; x < width; ++x)
            if ((mask[static_cast<std::size_t>(y * width + x)] != 0) == feature_value)
                row[static_cast<std::size_t>(x)] = 0.0;
        rows[static_cast<std::size_t>(y)] = edt_1d(row);
    }
    std::vector<double> output(static_cast<std::size_t>(width * height));
    for (int x = 0; x < width; ++x) {
        std::vector<double> column(static_cast<std::size_t>(height));
        for (int y = 0; y < height; ++y) column[y] = rows[y][x];
        column = edt_1d(column);
        for (int y = 0; y < height; ++y)
            output[static_cast<std::size_t>(y * width + x)] =
                column[y] < kInf ? std::sqrt(column[y]) :
                std::numeric_limits<double>::infinity();
    }
    return output;
}
}  // namespace

std::vector<double> signed_distance_field(const std::vector<std::uint8_t>& mask,
                                          int width, int height) {
    if (width <= 0 || height <= 0 ||
        mask.size() != static_cast<std::size_t>(width * height))
        throw std::invalid_argument("mask size must equal positive width * height");
    const auto inside = distance_to(mask, width, height, true);
    const auto outside = distance_to(mask, width, height, false);
    std::vector<double> result(mask.size());
    for (std::size_t index = 0; index < result.size(); ++index)
        result[index] = outside[index] - inside[index];
    return result;
}

}  // namespace vector_engine
