#include "car.h"

namespace {
#define DIM 9
#define EDIM 9
#define MEDIM 9
typedef void (*Hfun)(double *, double *, double *);

double mass;

void set_mass(double x){ mass = x;}

double rotational_inertia;

void set_rotational_inertia(double x){ rotational_inertia = x;}

double center_to_front;

void set_center_to_front(double x){ center_to_front = x;}

double center_to_rear;

void set_center_to_rear(double x){ center_to_rear = x;}

double stiffness_front;

void set_stiffness_front(double x){ stiffness_front = x;}

double stiffness_rear;

void set_stiffness_rear(double x){ stiffness_rear = x;}
const static double MAHA_THRESH_25 = 3.8414588206941227;
const static double MAHA_THRESH_24 = 5.991464547107981;
const static double MAHA_THRESH_30 = 3.8414588206941227;
const static double MAHA_THRESH_26 = 3.8414588206941227;
const static double MAHA_THRESH_27 = 3.8414588206941227;
const static double MAHA_THRESH_29 = 3.8414588206941227;
const static double MAHA_THRESH_28 = 3.8414588206941227;
const static double MAHA_THRESH_31 = 3.8414588206941227;

/******************************************************************************
 *                      Code generated with SymPy 1.14.0                      *
 *                                                                            *
 *              See http://www.sympy.org/ for more information.               *
 *                                                                            *
 *                         This file is part of 'ekf'                         *
 ******************************************************************************/
void err_fun(double *nom_x, double *delta_x, double *out_2225772217073868110) {
   out_2225772217073868110[0] = delta_x[0] + nom_x[0];
   out_2225772217073868110[1] = delta_x[1] + nom_x[1];
   out_2225772217073868110[2] = delta_x[2] + nom_x[2];
   out_2225772217073868110[3] = delta_x[3] + nom_x[3];
   out_2225772217073868110[4] = delta_x[4] + nom_x[4];
   out_2225772217073868110[5] = delta_x[5] + nom_x[5];
   out_2225772217073868110[6] = delta_x[6] + nom_x[6];
   out_2225772217073868110[7] = delta_x[7] + nom_x[7];
   out_2225772217073868110[8] = delta_x[8] + nom_x[8];
}
void inv_err_fun(double *nom_x, double *true_x, double *out_7557565541164638759) {
   out_7557565541164638759[0] = -nom_x[0] + true_x[0];
   out_7557565541164638759[1] = -nom_x[1] + true_x[1];
   out_7557565541164638759[2] = -nom_x[2] + true_x[2];
   out_7557565541164638759[3] = -nom_x[3] + true_x[3];
   out_7557565541164638759[4] = -nom_x[4] + true_x[4];
   out_7557565541164638759[5] = -nom_x[5] + true_x[5];
   out_7557565541164638759[6] = -nom_x[6] + true_x[6];
   out_7557565541164638759[7] = -nom_x[7] + true_x[7];
   out_7557565541164638759[8] = -nom_x[8] + true_x[8];
}
void H_mod_fun(double *state, double *out_3700601390112478894) {
   out_3700601390112478894[0] = 1.0;
   out_3700601390112478894[1] = 0.0;
   out_3700601390112478894[2] = 0.0;
   out_3700601390112478894[3] = 0.0;
   out_3700601390112478894[4] = 0.0;
   out_3700601390112478894[5] = 0.0;
   out_3700601390112478894[6] = 0.0;
   out_3700601390112478894[7] = 0.0;
   out_3700601390112478894[8] = 0.0;
   out_3700601390112478894[9] = 0.0;
   out_3700601390112478894[10] = 1.0;
   out_3700601390112478894[11] = 0.0;
   out_3700601390112478894[12] = 0.0;
   out_3700601390112478894[13] = 0.0;
   out_3700601390112478894[14] = 0.0;
   out_3700601390112478894[15] = 0.0;
   out_3700601390112478894[16] = 0.0;
   out_3700601390112478894[17] = 0.0;
   out_3700601390112478894[18] = 0.0;
   out_3700601390112478894[19] = 0.0;
   out_3700601390112478894[20] = 1.0;
   out_3700601390112478894[21] = 0.0;
   out_3700601390112478894[22] = 0.0;
   out_3700601390112478894[23] = 0.0;
   out_3700601390112478894[24] = 0.0;
   out_3700601390112478894[25] = 0.0;
   out_3700601390112478894[26] = 0.0;
   out_3700601390112478894[27] = 0.0;
   out_3700601390112478894[28] = 0.0;
   out_3700601390112478894[29] = 0.0;
   out_3700601390112478894[30] = 1.0;
   out_3700601390112478894[31] = 0.0;
   out_3700601390112478894[32] = 0.0;
   out_3700601390112478894[33] = 0.0;
   out_3700601390112478894[34] = 0.0;
   out_3700601390112478894[35] = 0.0;
   out_3700601390112478894[36] = 0.0;
   out_3700601390112478894[37] = 0.0;
   out_3700601390112478894[38] = 0.0;
   out_3700601390112478894[39] = 0.0;
   out_3700601390112478894[40] = 1.0;
   out_3700601390112478894[41] = 0.0;
   out_3700601390112478894[42] = 0.0;
   out_3700601390112478894[43] = 0.0;
   out_3700601390112478894[44] = 0.0;
   out_3700601390112478894[45] = 0.0;
   out_3700601390112478894[46] = 0.0;
   out_3700601390112478894[47] = 0.0;
   out_3700601390112478894[48] = 0.0;
   out_3700601390112478894[49] = 0.0;
   out_3700601390112478894[50] = 1.0;
   out_3700601390112478894[51] = 0.0;
   out_3700601390112478894[52] = 0.0;
   out_3700601390112478894[53] = 0.0;
   out_3700601390112478894[54] = 0.0;
   out_3700601390112478894[55] = 0.0;
   out_3700601390112478894[56] = 0.0;
   out_3700601390112478894[57] = 0.0;
   out_3700601390112478894[58] = 0.0;
   out_3700601390112478894[59] = 0.0;
   out_3700601390112478894[60] = 1.0;
   out_3700601390112478894[61] = 0.0;
   out_3700601390112478894[62] = 0.0;
   out_3700601390112478894[63] = 0.0;
   out_3700601390112478894[64] = 0.0;
   out_3700601390112478894[65] = 0.0;
   out_3700601390112478894[66] = 0.0;
   out_3700601390112478894[67] = 0.0;
   out_3700601390112478894[68] = 0.0;
   out_3700601390112478894[69] = 0.0;
   out_3700601390112478894[70] = 1.0;
   out_3700601390112478894[71] = 0.0;
   out_3700601390112478894[72] = 0.0;
   out_3700601390112478894[73] = 0.0;
   out_3700601390112478894[74] = 0.0;
   out_3700601390112478894[75] = 0.0;
   out_3700601390112478894[76] = 0.0;
   out_3700601390112478894[77] = 0.0;
   out_3700601390112478894[78] = 0.0;
   out_3700601390112478894[79] = 0.0;
   out_3700601390112478894[80] = 1.0;
}
void f_fun(double *state, double dt, double *out_9053440083114371104) {
   out_9053440083114371104[0] = state[0];
   out_9053440083114371104[1] = state[1];
   out_9053440083114371104[2] = state[2];
   out_9053440083114371104[3] = state[3];
   out_9053440083114371104[4] = state[4];
   out_9053440083114371104[5] = dt*((-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]))*state[6] - 9.8100000000000005*state[8] + stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*state[1]) + (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*state[4])) + state[5];
   out_9053440083114371104[6] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*state[4])) + state[6];
   out_9053440083114371104[7] = state[7];
   out_9053440083114371104[8] = state[8];
}
void F_fun(double *state, double dt, double *out_7771674578251097228) {
   out_7771674578251097228[0] = 1;
   out_7771674578251097228[1] = 0;
   out_7771674578251097228[2] = 0;
   out_7771674578251097228[3] = 0;
   out_7771674578251097228[4] = 0;
   out_7771674578251097228[5] = 0;
   out_7771674578251097228[6] = 0;
   out_7771674578251097228[7] = 0;
   out_7771674578251097228[8] = 0;
   out_7771674578251097228[9] = 0;
   out_7771674578251097228[10] = 1;
   out_7771674578251097228[11] = 0;
   out_7771674578251097228[12] = 0;
   out_7771674578251097228[13] = 0;
   out_7771674578251097228[14] = 0;
   out_7771674578251097228[15] = 0;
   out_7771674578251097228[16] = 0;
   out_7771674578251097228[17] = 0;
   out_7771674578251097228[18] = 0;
   out_7771674578251097228[19] = 0;
   out_7771674578251097228[20] = 1;
   out_7771674578251097228[21] = 0;
   out_7771674578251097228[22] = 0;
   out_7771674578251097228[23] = 0;
   out_7771674578251097228[24] = 0;
   out_7771674578251097228[25] = 0;
   out_7771674578251097228[26] = 0;
   out_7771674578251097228[27] = 0;
   out_7771674578251097228[28] = 0;
   out_7771674578251097228[29] = 0;
   out_7771674578251097228[30] = 1;
   out_7771674578251097228[31] = 0;
   out_7771674578251097228[32] = 0;
   out_7771674578251097228[33] = 0;
   out_7771674578251097228[34] = 0;
   out_7771674578251097228[35] = 0;
   out_7771674578251097228[36] = 0;
   out_7771674578251097228[37] = 0;
   out_7771674578251097228[38] = 0;
   out_7771674578251097228[39] = 0;
   out_7771674578251097228[40] = 1;
   out_7771674578251097228[41] = 0;
   out_7771674578251097228[42] = 0;
   out_7771674578251097228[43] = 0;
   out_7771674578251097228[44] = 0;
   out_7771674578251097228[45] = dt*(stiffness_front*(-state[2] - state[3] + state[7])/(mass*state[1]) + (-stiffness_front - stiffness_rear)*state[5]/(mass*state[4]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[6]/(mass*state[4]));
   out_7771674578251097228[46] = -dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(mass*pow(state[1], 2));
   out_7771674578251097228[47] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_7771674578251097228[48] = -dt*stiffness_front*state[0]/(mass*state[1]);
   out_7771674578251097228[49] = dt*((-1 - (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*pow(state[4], 2)))*state[6] - (-stiffness_front*state[0] - stiffness_rear*state[0])*state[5]/(mass*pow(state[4], 2)));
   out_7771674578251097228[50] = dt*(-stiffness_front*state[0] - stiffness_rear*state[0])/(mass*state[4]) + 1;
   out_7771674578251097228[51] = dt*(-state[4] + (-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(mass*state[4]));
   out_7771674578251097228[52] = dt*stiffness_front*state[0]/(mass*state[1]);
   out_7771674578251097228[53] = -9.8100000000000005*dt;
   out_7771674578251097228[54] = dt*(center_to_front*stiffness_front*(-state[2] - state[3] + state[7])/(rotational_inertia*state[1]) + (-center_to_front*stiffness_front + center_to_rear*stiffness_rear)*state[5]/(rotational_inertia*state[4]) + (-pow(center_to_front, 2)*stiffness_front - pow(center_to_rear, 2)*stiffness_rear)*state[6]/(rotational_inertia*state[4]));
   out_7771674578251097228[55] = -center_to_front*dt*stiffness_front*(-state[2] - state[3] + state[7])*state[0]/(rotational_inertia*pow(state[1], 2));
   out_7771674578251097228[56] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_7771674578251097228[57] = -center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_7771674578251097228[58] = dt*(-(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])*state[5]/(rotational_inertia*pow(state[4], 2)) - (-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])*state[6]/(rotational_inertia*pow(state[4], 2)));
   out_7771674578251097228[59] = dt*(-center_to_front*stiffness_front*state[0] + center_to_rear*stiffness_rear*state[0])/(rotational_inertia*state[4]);
   out_7771674578251097228[60] = dt*(-pow(center_to_front, 2)*stiffness_front*state[0] - pow(center_to_rear, 2)*stiffness_rear*state[0])/(rotational_inertia*state[4]) + 1;
   out_7771674578251097228[61] = center_to_front*dt*stiffness_front*state[0]/(rotational_inertia*state[1]);
   out_7771674578251097228[62] = 0;
   out_7771674578251097228[63] = 0;
   out_7771674578251097228[64] = 0;
   out_7771674578251097228[65] = 0;
   out_7771674578251097228[66] = 0;
   out_7771674578251097228[67] = 0;
   out_7771674578251097228[68] = 0;
   out_7771674578251097228[69] = 0;
   out_7771674578251097228[70] = 1;
   out_7771674578251097228[71] = 0;
   out_7771674578251097228[72] = 0;
   out_7771674578251097228[73] = 0;
   out_7771674578251097228[74] = 0;
   out_7771674578251097228[75] = 0;
   out_7771674578251097228[76] = 0;
   out_7771674578251097228[77] = 0;
   out_7771674578251097228[78] = 0;
   out_7771674578251097228[79] = 0;
   out_7771674578251097228[80] = 1;
}
void h_25(double *state, double *unused, double *out_5378663998965747519) {
   out_5378663998965747519[0] = state[6];
}
void H_25(double *state, double *unused, double *out_6824804650623212917) {
   out_6824804650623212917[0] = 0;
   out_6824804650623212917[1] = 0;
   out_6824804650623212917[2] = 0;
   out_6824804650623212917[3] = 0;
   out_6824804650623212917[4] = 0;
   out_6824804650623212917[5] = 0;
   out_6824804650623212917[6] = 1;
   out_6824804650623212917[7] = 0;
   out_6824804650623212917[8] = 0;
}
void h_24(double *state, double *unused, double *out_7449396400121290430) {
   out_7449396400121290430[0] = state[4];
   out_7449396400121290430[1] = state[5];
}
void H_24(double *state, double *unused, double *out_3266879051820889781) {
   out_3266879051820889781[0] = 0;
   out_3266879051820889781[1] = 0;
   out_3266879051820889781[2] = 0;
   out_3266879051820889781[3] = 0;
   out_3266879051820889781[4] = 1;
   out_3266879051820889781[5] = 0;
   out_3266879051820889781[6] = 0;
   out_3266879051820889781[7] = 0;
   out_3266879051820889781[8] = 0;
   out_3266879051820889781[9] = 0;
   out_3266879051820889781[10] = 0;
   out_3266879051820889781[11] = 0;
   out_3266879051820889781[12] = 0;
   out_3266879051820889781[13] = 0;
   out_3266879051820889781[14] = 1;
   out_3266879051820889781[15] = 0;
   out_3266879051820889781[16] = 0;
   out_3266879051820889781[17] = 0;
}
void h_30(double *state, double *unused, double *out_5103469936681241630) {
   out_5103469936681241630[0] = state[4];
}
void H_30(double *state, double *unused, double *out_7094243092958730501) {
   out_7094243092958730501[0] = 0;
   out_7094243092958730501[1] = 0;
   out_7094243092958730501[2] = 0;
   out_7094243092958730501[3] = 0;
   out_7094243092958730501[4] = 1;
   out_7094243092958730501[5] = 0;
   out_7094243092958730501[6] = 0;
   out_7094243092958730501[7] = 0;
   out_7094243092958730501[8] = 0;
}
void h_26(double *state, double *unused, double *out_6551031163396578207) {
   out_6551031163396578207[0] = state[7];
}
void H_26(double *state, double *unused, double *out_7880436104212282475) {
   out_7880436104212282475[0] = 0;
   out_7880436104212282475[1] = 0;
   out_7880436104212282475[2] = 0;
   out_7880436104212282475[3] = 0;
   out_7880436104212282475[4] = 0;
   out_7880436104212282475[5] = 0;
   out_7880436104212282475[6] = 0;
   out_7880436104212282475[7] = 1;
   out_7880436104212282475[8] = 0;
}
void h_27(double *state, double *unused, double *out_376990731304901874) {
   out_376990731304901874[0] = state[3];
}
void H_27(double *state, double *unused, double *out_4919479781158305590) {
   out_4919479781158305590[0] = 0;
   out_4919479781158305590[1] = 0;
   out_4919479781158305590[2] = 0;
   out_4919479781158305590[3] = 1;
   out_4919479781158305590[4] = 0;
   out_4919479781158305590[5] = 0;
   out_4919479781158305590[6] = 0;
   out_4919479781158305590[7] = 0;
   out_4919479781158305590[8] = 0;
}
void h_29(double *state, double *unused, double *out_2570735259050583087) {
   out_2570735259050583087[0] = state[1];
}
void H_29(double *state, double *unused, double *out_7604474437273122685) {
   out_7604474437273122685[0] = 0;
   out_7604474437273122685[1] = 1;
   out_7604474437273122685[2] = 0;
   out_7604474437273122685[3] = 0;
   out_7604474437273122685[4] = 0;
   out_7604474437273122685[5] = 0;
   out_7604474437273122685[6] = 0;
   out_7604474437273122685[7] = 0;
   out_7604474437273122685[8] = 0;
}
void h_28(double *state, double *unused, double *out_4624682536355943771) {
   out_4624682536355943771[0] = state[0];
}
void H_28(double *state, double *unused, double *out_2522075420203592111) {
   out_2522075420203592111[0] = 1;
   out_2522075420203592111[1] = 0;
   out_2522075420203592111[2] = 0;
   out_2522075420203592111[3] = 0;
   out_2522075420203592111[4] = 0;
   out_2522075420203592111[5] = 0;
   out_2522075420203592111[6] = 0;
   out_2522075420203592111[7] = 0;
   out_2522075420203592111[8] = 0;
}
void h_31(double *state, double *unused, double *out_9016113527219769869) {
   out_9016113527219769869[0] = state[8];
}
void H_31(double *state, double *unused, double *out_7254228001978930999) {
   out_7254228001978930999[0] = 0;
   out_7254228001978930999[1] = 0;
   out_7254228001978930999[2] = 0;
   out_7254228001978930999[3] = 0;
   out_7254228001978930999[4] = 0;
   out_7254228001978930999[5] = 0;
   out_7254228001978930999[6] = 0;
   out_7254228001978930999[7] = 0;
   out_7254228001978930999[8] = 1;
}
#include <eigen3/Eigen/Dense>
#include <iostream>

typedef Eigen::Matrix<double, DIM, DIM, Eigen::RowMajor> DDM;
typedef Eigen::Matrix<double, EDIM, EDIM, Eigen::RowMajor> EEM;
typedef Eigen::Matrix<double, DIM, EDIM, Eigen::RowMajor> DEM;

void predict(double *in_x, double *in_P, double *in_Q, double dt) {
  typedef Eigen::Matrix<double, MEDIM, MEDIM, Eigen::RowMajor> RRM;

  double nx[DIM] = {0};
  double in_F[EDIM*EDIM] = {0};

  // functions from sympy
  f_fun(in_x, dt, nx);
  F_fun(in_x, dt, in_F);


  EEM F(in_F);
  EEM P(in_P);
  EEM Q(in_Q);

  RRM F_main = F.topLeftCorner(MEDIM, MEDIM);
  P.topLeftCorner(MEDIM, MEDIM) = (F_main * P.topLeftCorner(MEDIM, MEDIM)) * F_main.transpose();
  P.topRightCorner(MEDIM, EDIM - MEDIM) = F_main * P.topRightCorner(MEDIM, EDIM - MEDIM);
  P.bottomLeftCorner(EDIM - MEDIM, MEDIM) = P.bottomLeftCorner(EDIM - MEDIM, MEDIM) * F_main.transpose();

  P = P + dt*Q;

  // copy out state
  memcpy(in_x, nx, DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
}

// note: extra_args dim only correct when null space projecting
// otherwise 1
template <int ZDIM, int EADIM, bool MAHA_TEST>
void update(double *in_x, double *in_P, Hfun h_fun, Hfun H_fun, Hfun Hea_fun, double *in_z, double *in_R, double *in_ea, double MAHA_THRESHOLD) {
  typedef Eigen::Matrix<double, ZDIM, ZDIM, Eigen::RowMajor> ZZM;
  typedef Eigen::Matrix<double, ZDIM, DIM, Eigen::RowMajor> ZDM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, EDIM, Eigen::RowMajor> XEM;
  //typedef Eigen::Matrix<double, EDIM, ZDIM, Eigen::RowMajor> EZM;
  typedef Eigen::Matrix<double, Eigen::Dynamic, 1> X1M;
  typedef Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor> XXM;

  double in_hx[ZDIM] = {0};
  double in_H[ZDIM * DIM] = {0};
  double in_H_mod[EDIM * DIM] = {0};
  double delta_x[EDIM] = {0};
  double x_new[DIM] = {0};


  // state x, P
  Eigen::Matrix<double, ZDIM, 1> z(in_z);
  EEM P(in_P);
  ZZM pre_R(in_R);

  // functions from sympy
  h_fun(in_x, in_ea, in_hx);
  H_fun(in_x, in_ea, in_H);
  ZDM pre_H(in_H);

  // get y (y = z - hx)
  Eigen::Matrix<double, ZDIM, 1> pre_y(in_hx); pre_y = z - pre_y;
  X1M y; XXM H; XXM R;
  if (Hea_fun){
    typedef Eigen::Matrix<double, ZDIM, EADIM, Eigen::RowMajor> ZAM;
    double in_Hea[ZDIM * EADIM] = {0};
    Hea_fun(in_x, in_ea, in_Hea);
    ZAM Hea(in_Hea);
    XXM A = Hea.transpose().fullPivLu().kernel();


    y = A.transpose() * pre_y;
    H = A.transpose() * pre_H;
    R = A.transpose() * pre_R * A;
  } else {
    y = pre_y;
    H = pre_H;
    R = pre_R;
  }
  // get modified H
  H_mod_fun(in_x, in_H_mod);
  DEM H_mod(in_H_mod);
  XEM H_err = H * H_mod;

  // Do mahalobis distance test
  if (MAHA_TEST){
    XXM a = (H_err * P * H_err.transpose() + R).inverse();
    double maha_dist = y.transpose() * a * y;
    if (maha_dist > MAHA_THRESHOLD){
      R = 1.0e16 * R;
    }
  }

  // Outlier resilient weighting
  double weight = 1;//(1.5)/(1 + y.squaredNorm()/R.sum());

  // kalman gains and I_KH
  XXM S = ((H_err * P) * H_err.transpose()) + R/weight;
  XEM KT = S.fullPivLu().solve(H_err * P.transpose());
  //EZM K = KT.transpose(); TODO: WHY DOES THIS NOT COMPILE?
  //EZM K = S.fullPivLu().solve(H_err * P.transpose()).transpose();
  //std::cout << "Here is the matrix rot:\n" << K << std::endl;
  EEM I_KH = Eigen::Matrix<double, EDIM, EDIM>::Identity() - (KT.transpose() * H_err);

  // update state by injecting dx
  Eigen::Matrix<double, EDIM, 1> dx(delta_x);
  dx  = (KT.transpose() * y);
  memcpy(delta_x, dx.data(), EDIM * sizeof(double));
  err_fun(in_x, delta_x, x_new);
  Eigen::Matrix<double, DIM, 1> x(x_new);

  // update cov
  P = ((I_KH * P) * I_KH.transpose()) + ((KT.transpose() * R) * KT);

  // copy out state
  memcpy(in_x, x.data(), DIM * sizeof(double));
  memcpy(in_P, P.data(), EDIM * EDIM * sizeof(double));
  memcpy(in_z, y.data(), y.rows() * sizeof(double));
}




}
extern "C" {

void car_update_25(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_25, H_25, NULL, in_z, in_R, in_ea, MAHA_THRESH_25);
}
void car_update_24(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<2, 3, 0>(in_x, in_P, h_24, H_24, NULL, in_z, in_R, in_ea, MAHA_THRESH_24);
}
void car_update_30(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_30, H_30, NULL, in_z, in_R, in_ea, MAHA_THRESH_30);
}
void car_update_26(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_26, H_26, NULL, in_z, in_R, in_ea, MAHA_THRESH_26);
}
void car_update_27(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_27, H_27, NULL, in_z, in_R, in_ea, MAHA_THRESH_27);
}
void car_update_29(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_29, H_29, NULL, in_z, in_R, in_ea, MAHA_THRESH_29);
}
void car_update_28(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_28, H_28, NULL, in_z, in_R, in_ea, MAHA_THRESH_28);
}
void car_update_31(double *in_x, double *in_P, double *in_z, double *in_R, double *in_ea) {
  update<1, 3, 0>(in_x, in_P, h_31, H_31, NULL, in_z, in_R, in_ea, MAHA_THRESH_31);
}
void car_err_fun(double *nom_x, double *delta_x, double *out_2225772217073868110) {
  err_fun(nom_x, delta_x, out_2225772217073868110);
}
void car_inv_err_fun(double *nom_x, double *true_x, double *out_7557565541164638759) {
  inv_err_fun(nom_x, true_x, out_7557565541164638759);
}
void car_H_mod_fun(double *state, double *out_3700601390112478894) {
  H_mod_fun(state, out_3700601390112478894);
}
void car_f_fun(double *state, double dt, double *out_9053440083114371104) {
  f_fun(state,  dt, out_9053440083114371104);
}
void car_F_fun(double *state, double dt, double *out_7771674578251097228) {
  F_fun(state,  dt, out_7771674578251097228);
}
void car_h_25(double *state, double *unused, double *out_5378663998965747519) {
  h_25(state, unused, out_5378663998965747519);
}
void car_H_25(double *state, double *unused, double *out_6824804650623212917) {
  H_25(state, unused, out_6824804650623212917);
}
void car_h_24(double *state, double *unused, double *out_7449396400121290430) {
  h_24(state, unused, out_7449396400121290430);
}
void car_H_24(double *state, double *unused, double *out_3266879051820889781) {
  H_24(state, unused, out_3266879051820889781);
}
void car_h_30(double *state, double *unused, double *out_5103469936681241630) {
  h_30(state, unused, out_5103469936681241630);
}
void car_H_30(double *state, double *unused, double *out_7094243092958730501) {
  H_30(state, unused, out_7094243092958730501);
}
void car_h_26(double *state, double *unused, double *out_6551031163396578207) {
  h_26(state, unused, out_6551031163396578207);
}
void car_H_26(double *state, double *unused, double *out_7880436104212282475) {
  H_26(state, unused, out_7880436104212282475);
}
void car_h_27(double *state, double *unused, double *out_376990731304901874) {
  h_27(state, unused, out_376990731304901874);
}
void car_H_27(double *state, double *unused, double *out_4919479781158305590) {
  H_27(state, unused, out_4919479781158305590);
}
void car_h_29(double *state, double *unused, double *out_2570735259050583087) {
  h_29(state, unused, out_2570735259050583087);
}
void car_H_29(double *state, double *unused, double *out_7604474437273122685) {
  H_29(state, unused, out_7604474437273122685);
}
void car_h_28(double *state, double *unused, double *out_4624682536355943771) {
  h_28(state, unused, out_4624682536355943771);
}
void car_H_28(double *state, double *unused, double *out_2522075420203592111) {
  H_28(state, unused, out_2522075420203592111);
}
void car_h_31(double *state, double *unused, double *out_9016113527219769869) {
  h_31(state, unused, out_9016113527219769869);
}
void car_H_31(double *state, double *unused, double *out_7254228001978930999) {
  H_31(state, unused, out_7254228001978930999);
}
void car_predict(double *in_x, double *in_P, double *in_Q, double dt) {
  predict(in_x, in_P, in_Q, dt);
}
void car_set_mass(double x) {
  set_mass(x);
}
void car_set_rotational_inertia(double x) {
  set_rotational_inertia(x);
}
void car_set_center_to_front(double x) {
  set_center_to_front(x);
}
void car_set_center_to_rear(double x) {
  set_center_to_rear(x);
}
void car_set_stiffness_front(double x) {
  set_stiffness_front(x);
}
void car_set_stiffness_rear(double x) {
  set_stiffness_rear(x);
}
}

const EKF car = {
  .name = "car",
  .kinds = { 25, 24, 30, 26, 27, 29, 28, 31 },
  .feature_kinds = {  },
  .f_fun = car_f_fun,
  .F_fun = car_F_fun,
  .err_fun = car_err_fun,
  .inv_err_fun = car_inv_err_fun,
  .H_mod_fun = car_H_mod_fun,
  .predict = car_predict,
  .hs = {
    { 25, car_h_25 },
    { 24, car_h_24 },
    { 30, car_h_30 },
    { 26, car_h_26 },
    { 27, car_h_27 },
    { 29, car_h_29 },
    { 28, car_h_28 },
    { 31, car_h_31 },
  },
  .Hs = {
    { 25, car_H_25 },
    { 24, car_H_24 },
    { 30, car_H_30 },
    { 26, car_H_26 },
    { 27, car_H_27 },
    { 29, car_H_29 },
    { 28, car_H_28 },
    { 31, car_H_31 },
  },
  .updates = {
    { 25, car_update_25 },
    { 24, car_update_24 },
    { 30, car_update_30 },
    { 26, car_update_26 },
    { 27, car_update_27 },
    { 29, car_update_29 },
    { 28, car_update_28 },
    { 31, car_update_31 },
  },
  .Hes = {
  },
  .sets = {
    { "mass", car_set_mass },
    { "rotational_inertia", car_set_rotational_inertia },
    { "center_to_front", car_set_center_to_front },
    { "center_to_rear", car_set_center_to_rear },
    { "stiffness_front", car_set_stiffness_front },
    { "stiffness_rear", car_set_stiffness_rear },
  },
  .extra_routines = {
  },
};

ekf_lib_init(car)
