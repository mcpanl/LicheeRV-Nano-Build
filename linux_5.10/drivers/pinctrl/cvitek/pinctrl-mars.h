/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Copyright (C) Cvitek Co., Ltd. 2019-2020. All rights reserved.
 *
 * File Name: pinctrl-cv1822.h
 * Description:
 */

#ifndef __PINCTRL_CV181X_H__
#define __PINCTRL_CV181X_H__

#include "../core.h"
#include "cv181x_pinlist_swconfig.h"
#include "cv181x_reg_fmux_gpio.h"

#define CVITEK_PINMUX_REG_LAST (FMUX_GPIO_FUNCSEL_PAD_AUD_AOUTR + 4)

#define PINMUX_BASE 0x03001000
#define PINMUX_MASK(PIN_NAME) FMUX_GPIO_FUNCSEL_##PIN_NAME##_MASK
#define PINMUX_OFFSET(PIN_NAME) FMUX_GPIO_FUNCSEL_##PIN_NAME##_OFFSET
#define PINMUX_VALUE(PIN_NAME, FUNC_NAME) PIN_NAME##__##FUNC_NAME
#define PINMUX_CONFIG(PIN_NAME, FUNC_NAME) \
		mmio_clrsetbits_32(PINMUX_BASE + FMUX_GPIO_FUNCSEL_##PIN_NAME, \
						   PINMUX_MASK(PIN_NAME) << PINMUX_OFFSET(PIN_NAME), \
						   PINMUX_VALUE(PIN_NAME, FUNC_NAME))

static inline void mmio_clrsetbits_32(uintptr_t addr,
				      uint32_t clear,
				      uint32_t set)
{
	void __iomem *tpreg;

	tpreg = ioremap(addr, 0x4);
	if (IS_ERR(tpreg)) {
		pr_err("ioremap %p failed\n", (void *)addr);
		return;
	}

	iowrite32((ioread32(tpreg) & ~clear) | set, tpreg);

	iounmap(tpreg);
}

#endif /* __PINCTRL_CV181X_H__ */
