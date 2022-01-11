#pragma once

#include <complex>
#include <vector>
#include <Eigen/Dense>

using namespace Eigen;


std::vector<VectorXd> cast_delta(double* delta, size_t delta_size, size_t lasers_size);
std::vector<Vector3d> cast_v(double* delta, size_t v_size);
VectorXd cast_y0_vectord(double* y0, size_t size);
VectorXcd cast_y0_vectorcd(std::complex<double>* y0, size_t size);
MatrixXcd cast_y0_matrixcd(std::complex<double>* y0, size_t size);
