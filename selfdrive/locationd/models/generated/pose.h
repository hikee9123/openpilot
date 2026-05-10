#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void pose_update_4(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_10(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_13(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_update_14(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void pose_err_fun(double *nom_x, double *delta_x, double *out_1103084970822345352);
void pose_inv_err_fun(double *nom_x, double *true_x, double *out_5459115001706413123);
void pose_H_mod_fun(double *state, double *out_7351235428474932421);
void pose_f_fun(double *state, double dt, double *out_5276878112375474914);
void pose_F_fun(double *state, double dt, double *out_8717321888493851934);
void pose_h_4(double *state, double *unused, double *out_8181067520651079542);
void pose_H_4(double *state, double *unused, double *out_1593126237582888921);
void pose_h_10(double *state, double *unused, double *out_4029725787131848622);
void pose_H_10(double *state, double *unused, double *out_7172679610378254733);
void pose_h_13(double *state, double *unused, double *out_473946471737287856);
void pose_H_13(double *state, double *unused, double *out_1619147587749443880);
void pose_h_14(double *state, double *unused, double *out_7656295873946429583);
void pose_H_14(double *state, double *unused, double *out_2370114618756595608);
void pose_predict(double *in_x, double *in_P, double *in_Q, double dt);
}