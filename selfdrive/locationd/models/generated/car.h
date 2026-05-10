#pragma once
#include "rednose/helpers/ekf.h"
extern "C" {
void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea);
void car_err_fun(double *nom_x, double *delta_x, double *out_2225772217073868110);
void car_inv_err_fun(double *nom_x, double *true_x, double *out_7557565541164638759);
void car_H_mod_fun(double *state, double *out_3700601390112478894);
void car_f_fun(double *state, double dt, double *out_9053440083114371104);
void car_F_fun(double *state, double dt, double *out_7771674578251097228);
void car_h_25(double *state, double *unused, double *out_5378663998965747519);
void car_H_25(double *state, double *unused, double *out_6824804650623212917);
void car_h_24(double *state, double *unused, double *out_7449396400121290430);
void car_H_24(double *state, double *unused, double *out_3266879051820889781);
void car_h_30(double *state, double *unused, double *out_5103469936681241630);
void car_H_30(double *state, double *unused, double *out_7094243092958730501);
void car_h_26(double *state, double *unused, double *out_6551031163396578207);
void car_H_26(double *state, double *unused, double *out_7880436104212282475);
void car_h_27(double *state, double *unused, double *out_376990731304901874);
void car_H_27(double *state, double *unused, double *out_4919479781158305590);
void car_h_29(double *state, double *unused, double *out_2570735259050583087);
void car_H_29(double *state, double *unused, double *out_7604474437273122685);
void car_h_28(double *state, double *unused, double *out_4624682536355943771);
void car_H_28(double *state, double *unused, double *out_2522075420203592111);
void car_h_31(double *state, double *unused, double *out_9016113527219769869);
void car_H_31(double *state, double *unused, double *out_7254228001978930999);
void car_predict(double *in_x, double *in_P, double *in_Q, double dt);
void car_set_mass(double x);
void car_set_rotational_inertia(double x);
void car_set_center_to_front(double x);
void car_set_center_to_rear(double x);
void car_set_stiffness_front(double x);
void car_set_stiffness_rear(double x);
}