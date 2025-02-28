// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

#ifndef OPENTITAN_SW_DEVICE_SILICON_CREATOR_MANUF_LIB_PERSONALIZE_H_
#define OPENTITAN_SW_DEVICE_SILICON_CREATOR_MANUF_LIB_PERSONALIZE_H_

#include "sw/device/lib/base/status.h"
#include "sw/device/lib/crypto/impl/ecc/p256_common.h"
#include "sw/device/lib/crypto/include/ecc.h"
#include "sw/device/lib/dif/dif_flash_ctrl.h"
#include "sw/device/lib/dif/dif_lc_ctrl.h"
#include "sw/device/lib/dif/dif_otp_ctrl.h"
#include "sw/device/lib/testing/json/provisioning_data.h"

#include "otp_ctrl_regs.h"  // Generated.

/**
 * Personalize device with unique secrets.
 *
 * The device is provisioned with a unique set of secrets, which are hidden from
 * software. These secrets include both:
 *
 * 1. roots of the key derivation function in the key manager,
 *   a. CreatorSeed (Flash - Info Page)
 *   b. OwnerSeed (Flash - Info Page)
 *   c. RootKey (OTP - SECRET2 Partition)
 * 2. the RMA unlock token (OTP - SECRET2 Partition)
 *
 * Preconditions:
 * - Device is in DEV, PROD, or PROD_END lifecycle state.
 * - Device has SW CSRNG data access.
 *
 * Note: The test will skip all programming steps and succeed if the SECRET2
 * partition is already locked. This is to facilitate test re-runs.
 *
 * The caller should reset the device after calling this function.
 *
 * @param flash_state Flash controller instance.
 * @param lc_ctrl Lifecycle controller instance.
 * @param otp_ctrl OTP controller instance.
 * @param[out] export_data UJSON struct of data to export from the device.
 * @return OK_STATUS on success.
 */
status_t manuf_personalize_device(dif_flash_ctrl_state_t *flash_state,
                                  const dif_lc_ctrl_t *lc_ctrl,
                                  const dif_otp_ctrl_t *otp_ctrl,
                                  manuf_personalize_t *export_data);

/**
 * Checks the device personalization end state.
 *
 * When personalization is complete, OTP SECRET2 partition should be locked.
 *
 * @param otp_ctrl OTP controller instance.
 * @return OK_STATUS if the SECRET2 OTP partition is locked.
 */
status_t manuf_personalize_device_check(const dif_otp_ctrl_t *otp_ctrl);

#endif  // OPENTITAN_SW_DEVICE_SILICON_CREATOR_MANUF_LIB_PERSONALIZE_H_
