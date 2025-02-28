/* Copyright lowRISC contributors. */
/* Licensed under the Apache License, Version 2.0, see LICENSE for details. */
/* SPDX-License-Identifier: Apache-2.0 */

/* Copyright 2016 The Chromium OS Authors. All rights reserved.
 * Use of this source code is governed by a BSD-style license that can be
 * found in the LICENSE.dcrypto file.
 *
 * Derived from code in
 * https://chromium.googlesource.com/chromiumos/platform/ec/+/refs/heads/cr50_stab/chip/g/dcrypto/dcrypto_p256.c
 */

 .globl p256_verify

 .text

 /**
 * P-256 ECDSA signature verification
 *
 * returns the affine x-coordinate of
 *         (x1, y1) = u1*G + u2*Q
 *         with u1 = z*s^-1 mod n  and  u2 = r*s^-1 mod n
 *         with G being the curve's base point,
 *              z being the message
 *              r, s being the signature
 *              Q being the public key.
 *
 * The routine computes the x1 coordinate and places it in dmem. x1 will be
 * reduced (mod n), however, the final comparison has to be performed on the
 * host side. The signature is valid if x1 == r.
 * This routine runs in variable time.
 *
 * @param[in]  dmem[msg]: message to be verified (256 bits)
 * @param[in]  dmem[r]:   r component of signature (256 bits)
 * @param[in]  dmem[s]:   s component of signature (256 bits)
 * @param[in]  dmem[x]:   affine x-coordinate of public key (256 bits)
 * @param[in]  dmem[y]:   affine y-coordinate of public key (256 bits)
 * @param[out] dmem[x_r]: dmem buffer for reduced affine x_r-coordinate (x_1)
 *
 * Flags: Flags have no meaning beyond the scope of this subroutine.
 *
 * clobbered registers: x2, x3, x13, x14, x17 to x24, w0 to w25
 * clobbered flag groups: FG0
 */
p256_verify:

  /* init all-zero register */
  bn.xor    w31, w31, w31

  /* load domain parameter b from dmem
     w27 <= b = dmem[p256_b] */
  li        x2, 27
  la        x3, p256_b
  bn.lid    x2, 0(x3)

  /* load r of signature from dmem: w24 = r = dmem[r] */
  la        x19, r
  li        x2, 11
  bn.lid    x2, 0(x19)

  /* setup modulus n (curve order) and Barrett constant
     MOD <= w29 <= n = dmem[p256_n]; w28 <= u_n = dmem[p256_u_n]  */
  li        x2, 29
  la        x3, p256_n
  bn.lid    x2, 0(x3)
  bn.wsrw   0, w29
  li        x2, 28
  la        x3, p256_u_n
  bn.lid    x2, 0(x3)

  /* load s of signature from dmem: w0 = s = dmem[s] */
  la        x20, s
  bn.lid    x0, 0(x20)

  /* goto 'fail' if w0 == w31 <=> s == 0 */
  bn.cmp    w0, w31
  csrrs     x2, 0x7c0, x0
  andi      x2, x2, 8
  bne       x2, x0, fail

  /* goto 'fail' if w0 >= w29 <=> s >= n */
  bn.cmp    w0, w29
  csrrs     x2, 0x7c0, x0
  andi      x2, x2, 1
  beq       x2, x0, fail

  /* w1 = s^-1  mod n */
  jal       x1, mod_inv_var

  /* load r of signature from dmem: w24 = r = dmem[r] */
  la        x19, r
  li        x2,  24
  bn.lid    x2, 0(x19)

  /* goto 'fail' if w24 == w31 <=> r == 0 */
  bn.cmp    w24, w31
  csrrs     x2, 0x7c0, x0
  andi      x2, x2, 8
  bne       x2, x0, fail

  /* goto 'fail' if w0 >= w29 <=> r >= n */
  bn.cmp    w24, w29
  csrrs     x2, 0x7c0, x0
  andi      x2, x2, 1
  beq       x2, x0, fail

  /* w25 = s^-1 = w1 */
  bn.mov    w25, w1

  /* u2 = w0 = w19 <= w24*w25 = r*s^-1 mod n */
  jal       x1, mod_mul_256x256
  bn.mov    w0, w19

  /* load message, w24 = msg = dmem[msg] */
  la        x18, msg
  li        x2, 24
  bn.lid    x2, 0(x18)

  /* u1 = w1 = w19 <= w24*w25 = w24*w1 = msg*s^-1 mod n */
  bn.mov    w25, w1
  jal       x1, mod_mul_256x256
  bn.mov    w1, w19

  /* setup modulus p and Barrett constant */
  li        x2, 29
  la        x3, p256_p
  bn.lid    x2, 0(x3)
  bn.wsrw   0, w29
  li        x2, 28
  la        x3, p256_u_p
  bn.lid    x2, 0(x3)

  /* load public key Q from dmem and use in projective form (set z to 1)
     Q = (w11, w12, w13) = (dmem[x], dmem[y], 1) */
  li        x2, 11
  la        x21, x
  bn.lid    x2++, 0(x21)
  la        x22, y
  bn.lid    x2, 0(x22)
  bn.addi   w13, w31, 1

  /* load base point G and use in projective form (set z to 1)
     G = (w8, w9, w10) = (x_g, y_g, 1) */
  li        x13, 8
  la        x23, p256_gx
  bn.lid    x13, 0(x23)
  li        x14, 9
  la        x24, p256_gy
  bn.lid    x14, 0(x24)
  bn.addi   w10, w31, 1

  /* The rest of the routine implements a variable time double-and-add
     algorithm. For the signature verification we need to compute the point
     C = (x1, y1) = u_1*G + u_2*Q. This can be done in a single
     double-and-add routine by using Shamir's Trick. */

  /* G+Q = (w3,w4,w5) = (w11,w12,w13) = (w8,w9,w10) (+) (w11,w12,w13) */
  jal       x1, proj_add
  bn.mov    w3, w11
  bn.mov    w4, w12
  bn.mov    w5, w13

  /* w2 = u_2 & u_0 = w0 & w1*/
  bn.and    w2, w0, w1

  /* init double and add algorithm with (0, 1, 0) */
  bn.mov    w11, w31
  bn.addi   w12, w31, 1
  bn.mov    w13, w31

  /* main loop with dicreasing index i (i=255 downto 0) */
  loopi     256, 31

    /* always double: C = (w11,w12,w13) <= 2 (*) C = 2 (*) (w11,w12,w13) */
    bn.mov    w8, w11
    bn.mov    w9, w12
    bn.mov    w10, w13
    jal       x1, proj_add

    /* if either  u_1[i] == 0 or u_2[i] == 0 jump to 'no_both' */
    bn.add    w2, w2, w2
    csrrs     x2, 0x7c0, x0
    andi      x2, x2, 1
    beq       x2, x0, no_both

    /* both bits at current index (u1[i] and u2[i]) are set:
       do C <= C + (P + Q) and jump to end */
    bn.mov    w8, w3
    bn.mov    w9, w4
    bn.mov    w10, w5
    jal       x1, proj_add
    jal       x0, no_q

    /* either u1[i] or u2[i] is set, but not both */
    no_both:

    /* if u2[i] is not set jump to 'no_g' */
    bn.add    w6, w0, w0
    csrrs     x2, 0x7c0, x0
    andi      x2, x2, 1
    beq       x2, x0, no_g

    /* u2[i] is set: do C <= C + Q */
    bn.lid    x13, 0(x21)
    bn.lid    x14, 0(x22)
    bn.addi   w10, w31, 1
    jal       x1, proj_add

    no_g:
    /* if u1[i] is not set jump to 'no_q' */
    bn.add    w6, w1, w1
    csrrs     x2, 0x7c0, x0
    andi      x2, x2, 1
    beq       x2, x0, no_q

    /* load base point x-coordinate
      w8 <= g_x = dmem [p256_gx]; w9 <= g_y = dmem[p256_gy] */
    bn.lid    x13, 0(x23)
    bn.lid    x14, 0(x24)

    /* u1[i] is set: do C <= C + G */
    bn.addi   w10, w31, 1
    jal       x1, proj_add

    no_q:
    /* left shift w0 and w1 to decrease index */
    bn.add    w0, w0, w0
    bn.add    w1, w1, w1

  /* compute inverse of z-coordinate: w1 = z_c^-1  mod p */
  bn.mov    w0, w13
  jal       x1, mod_inv_var

  /* convert x-coordinate of C back to affine: x1 = x_c * z_c^-1  mod p */
  bn.mov    w24, w1
  bn.mov    w25, w11
  jal       x1, mod_mul_256x256

  /* final reduction: w24 = x1 <= x1 mod n */
  la        x3, p256_n
  bn.lid    x0, 0(x3)
  bn.wsrw   0, w0
  bn.subm   w24, w19, w31

  fail:
  /* store affine x-coordinate in dmem: dmem[x_r] = w24 = x_r */
  la        x17, x_r
  li        x2, 24
  bn.sid    x2, 0(x17)

  ret

.section .bss

/* message digest */
.balign 32
.weak msg
msg:
  .zero 32

/* signature R */
.balign 32
.weak r
r:
  .zero 32

/* signature S */
.balign 32
.weak s
s:
  .zero 32

/* public key x-coordinate */
.balign 32
.weak x
x:
  .zero 32

/* public key y-coordinate */
.balign 32
.weak y
y:
  .zero 32

/* verification result x_r (aka x_1) */
.balign 32
.weak x_r
x_r:
  .zero 32
