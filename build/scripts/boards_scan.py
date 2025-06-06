#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK

import logging
import os
import re
import glob
import argparse
import itertools
import collections
import json
import os.path
from datetime import datetime

import build_helper
import kconfiglib

try:
    import argcomplete
except ImportError:
    argcomplete = None


build_helper.check_python_min_version()

Board = collections.namedtuple("Board", "chip, board, ddr_cfg, info")
Arch = collections.namedtuple("Arch", "chip, board")

ENVS_FROM_CONFIG = [
    "CHIP",
    "ARCH",
    "BOARD",
    "DDR_CFG",
    "ATF_SRC",
    "ATF_KEY_SEL",
    "KERNEL_SRC",
    "UBOOT_SRC",
    "USE_CCACHE",
    "MULTI_FIP",
    "STORAGE_TYPE",
    "NANDFLASH_PAGESIZE",
    "MW_VER",
    "SDK_VER",
    "SENSOR_TUNING_PARAM",
    "BUILD_TURNKEY_ACCESSGUARD",
    "BUILD_TURNKEY_IPC",
    "FLASH_SIZE_SHRINK",
    "DDR_64MB_SIZE",
    "PANEL_TUNING_PARAM",
    "PANEL_LANE_NUM_TUNING_PARAM",
    "PANEL_LANE_SWAP_TUNING_PARAM",
    "MTRACE",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan boards to generate env and configs"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        default="INFO",
        choices=["CRITICAL", "DEBUG", "ERROR", "INFO", "NOTSET", "WARNING"],
    )
    parser.add_argument("--logfile", type=str)
    parser.add_argument("--gen-build-kconfig", action="store_true")
    parser.add_argument("--scan-boards-config", action="store_true")
    parser.add_argument("--gen-board-env", type=str)
    parser.add_argument("--print-usage", action="store_true")
    parser.add_argument("--list-chip-arch", action="store_true")
    parser.add_argument("--get-chip-arch", action="store_true")
    parser.add_argument("--list-boards", type=str)
    parser.add_argument("--gen-board-its", dest="arch")
    parser.add_argument("--gen_single_board_its", action="store_true")
    parser.add_argument("--chip_name", dest="chip_name", type=str)
    parser.add_argument("--board_name", dest="board_name", type=str)
    parser.add_argument("--skip_ramdisk", action="store_true")

    if argcomplete:
        argcomplete.autocomplete(parser)

    return parser.parse_args()


def load_board_config(path):
    logging.debug("load %s", path)

    kconf = kconfiglib.Kconfig(
        build_helper.KCONFIG_PATH, suppress_traceback=True, warn=True
    )
    kconf.load_config(path)

    return kconf


def check_board_path(board_dir, chip, board):
    full_board_name = os.path.basename(board_dir)
    full_board_name2 = "%s_%s" % (chip, board)
    logging.debug("full_board_name=%s %s", full_board_name, full_board_name2)
    if full_board_name != full_board_name2:
        raise Exception(
            "The CHIP(%s)/BOARD(%s) in .config are not same as %s"
            % (chip, board, full_board_name)
        )


def scan_boards_config():
    configs_saved = sorted(glob.glob(build_helper.BOARD_KCONFIG_SAVED_GLOB))

    boards = {}

    for n, path in enumerate(configs_saved):
        *_, arch, board, conf = path.split("/")
        if arch == "default":
            continue

        kconf = load_board_config(path)

        check_board_path(
            os.path.dirname(path),
            kconf.syms["CHIP"].str_value,
            kconf.syms["BOARD"].str_value,
        )

        br = Board(
            kconf.syms["CHIP"].str_value,
            kconf.syms["BOARD"].str_value,
            kconf.syms["DDR_CFG"].str_value,
            "",
        )

        logging.debug("%d: %s", n, br)
        boards.setdefault(br.chip, []).append(br)

    return boards


kconfig_tmpl = """
#
# Automatically generated by boards_scan.py; DO NOT EDIT.
#

choice
  prompt "Chip selection"
  {chip_choice}
endchoice

{chip_arch_config}

config CHIP
  string
  {chip_config}

choice
  prompt "Board selection"
  {board_choice}
endchoice

config BOARD
  string
  {board_config}

choice
  prompt "DDR configuration selection"
  {ddr_cfg_choice}
endchoice

config DDR_CFG
  string
  {ddr_cfg_config}

"""


def board_dir_to_name(board_dir):
    chips = build_helper.get_chip_list()
    chip_list = list(itertools.chain(*chips.values()))

    m = re.search(
        r"^([0-9a-z]+)_(.+)$", os.path.basename(board_dir), flags=re.IGNORECASE
    )
    chip, br_name = m.groups()
    if chip not in chip_list:
        raise Exception(
            "%r of %r is unknown (missing in chip_list.json?)" % (chip, board_dir)
        )

    for chip_arch, xlist in chips.items():
        if chip in xlist:
            break
    else:
        raise Exception("Can't find CHIP_ARCH for %r" % chip)

    return chip_arch, chip, br_name


def gen_build_kconfig():
    board_list = collections.OrderedDict()
    config_str = {
        "chip_choice": "",
        "chip_arch_config": "",
        "chip_config": "",
        "board_choice": "",
        "board_config": "",
        "ddr_cfg_choice": "",
    }

    board_list.setdefault("none", []).append(Board("none", "none", "none", "none"))

    os.makedirs(build_helper.BUILD_OUTPUT_DIR, exist_ok=True)

    kconfig_path = os.path.join(build_helper.BUILD_OUTPUT_DIR, "Kconfig")

    for chip_arch in build_helper.get_chip_list():
        _dir = os.path.join(build_helper.BOARD_DIR, chip_arch)

        for board_dir in sorted(os.listdir(_dir)):
            if board_dir.strip() == "default":
                continue
            board_dir = os.path.join(build_helper.BOARD_DIR, chip_arch, board_dir)
            if not os.path.isdir(board_dir):
                continue

            logging.debug("board_dir=%r", board_dir)
            _, chip, br_name = board_dir_to_name(board_dir)

            cj_path = os.path.join(board_dir, "config.json")
            with open(cj_path, "r", encoding="utf-8") as fp:
                cj = json.load(fp)

            br = Board(chip, br_name, cj["ddr_cfg_list"], cj["board_information"])
            board_list.setdefault(chip, []).append(br)

    chip_list = build_helper.get_chip_list()
    chip_list["none"] = ["none"]
    chip_list_r = {c: k for k, v in chip_list.items() for c in v}

    config_str["chip_choice"] = "\n  ".join(
        (
            'config CHIP_{chip}\n    bool "{chip}"\n    select CHIP_ARCH_{chip_arch}'.format(
                chip=chip, chip_arch=chip_list_r[chip]
            ).strip()
            for chip in board_list.keys()
        )
    )

    config_str["chip_config"] = "\n  ".join(
        [
            'default "{chip}" if CHIP_{chip}'.format(chip=chip).strip()
            for chip in board_list.keys()
        ]
    )

    config_str["chip_arch_config"] = "\n".join(
        (
            "config CHIP_ARCH_{chip_arch}\n    def_bool n".format(
                chip_arch=chip_arch
            ).strip()
            for chip_arch in chip_list
        )
    )

    config_str["board_choice"] = "\n  ".join(
        [
            'config BOARD_{br}\n    bool "{br} ({br_info})"\n    depends on CHIP_{chip}'.format(
                chip=chip, br=br.board, br_info=br.info if br.info else "none"
            ).strip()
            for chip, br_list in board_list.items()
            for br in br_list
        ]
    )

    config_str["board_config"] = "\n  ".join(
        [
            'default "{br}" if BOARD_{br}'.format(br=br.board).strip()
            for _, br_list in board_list.items()
            for br in br_list
        ]
    )

    config_str["ddr_cfg_choice"] = "\n  ".join(
        [
            'config DDR_CFG_{ddf_cfg}\n    bool "{ddf_cfg}"\n    depends on CHIP_{chip} && BOARD_{br}'.format(
                chip=chip, br=br.board, ddf_cfg=ddr_cfg if ddr_cfg else "none"
            ).strip()
            for chip, br_list in board_list.items()
            for br in br_list
            for ddr_cfg in br.ddr_cfg
        ]
    )

    config_str["ddr_cfg_config"] = "\n  ".join(
        [
            'default "{ddf_cfg}" if DDR_CFG_{ddf_cfg}'.format(
                ddf_cfg=ddr_cfg if ddr_cfg else "none"
            ).strip()
            for chip, br_list in board_list.items()
            for br in br_list
            for ddr_cfg in br.ddr_cfg
        ]
    )

    kconfig = kconfig_tmpl.format(**config_str)
    with open(kconfig_path, "w") as fp:
        fp.write(kconfig)


def gen_build_env(boards):
    chips = build_helper.get_chip_list()

    # Chip definition
    for chip_arch, chip_list in sorted(chips.items()):
        chip_list = " ".join(sorted(chip_list))
        print("chip_%s=(%s)" % (chip_arch, chip_list))

    chip_cv_str = " ".join(sorted(itertools.chain(*chips.values())))
    print("chip_cv=(%s)" % chip_cv_str)
    # compatible with the original shell script
    print("chip_sel=(%s)" % chip_cv_str)

    # Platform definition
    print("subtype_sel=(palladium fpga asic)")

    # Board definition and information
    for chip, br_list in boards.items():
        n = 0
        br_list = [
            i for i in br_list if all(j not in i.board for j in ["palladium", "fpga"])
        ]
        br_list.sort()
        for n, br in enumerate(br_list):
            print('%s_board_sel[%d]="%s"' % (chip, n, br.board))
            print('%s_board_info[%d]="%s"' % (chip, n, br.info))
            print('%s_board_ddr_cfg[%d]="%s"' % (chip, n, br.ddr_cfg))


def gen_board_env(full_board_name):
    logging.debug("full_board_name=%s", full_board_name)

    config_path = os.path.join(build_helper.BUILD_REPO_DIR, ".config")
    with open(config_path, "r"):
        pass
    kconf = load_board_config(config_path)

    chips = build_helper.get_chip_list()
    chip = kconf.syms["CHIP"].str_value

    for chip_arch, chip_list in chips.items():
        if chip in chip_list:
            print('export CHIP_ARCH="%s"' % chip_arch.upper())
            break
    else:
        raise Exception("Can't find CHIP_ARCH for %r" % chip)

    print('export CHIP_SEGMENT="%s"' % build_helper.get_segment_from_chip(chip))

    for name in ENVS_FROM_CONFIG:
        print('export %s="%s"' % (name, kconf.syms[name].str_value))

    board = kconf.syms["BOARD"].str_value
    subtype = [i for i in ["palladium", "fpga"] if i in board]
    if subtype:
        subtype = subtype[0]
    else:
        subtype = "asic"
    print('export SUBTYPE="%s"' % subtype)


def get_chip_arch(board):
    if not board:
        return
    board_split, *_ = board.split("_")
    if board == board_split:
        return
    for arch, chips in build_helper.get_chip_list().items():
        if board_split in chips:
            print(arch)
            return


def list_chip_arch():
    for arch, chips in build_helper.get_chip_list().items():
        print("       ** %6s ** -> %s" % (arch, chips))


def list_boards_by_chip_arch(chip_arch):
    boards = {}
    if chip_arch not in build_helper.get_chip_list():
        print(" \033[1;31;47m Input chip arch '", chip_arch, "' is ERROR\033[0m")
        return
    for arch in build_helper.get_chip_list()[chip_arch]:
        boards[arch] = []
    board_dir = os.path.join(build_helper.BOARD_DIR, chip_arch)
    for board in sorted(os.listdir(board_dir)):
        m = re.search(r"^([0-9a-z]+)_(.+)$", board, flags=re.IGNORECASE)
        chip, _ = m.groups()

        conf_path = os.path.join(board_dir, board, "config.json")
        with open(conf_path, "r", encoding="utf-8") as fp:
            conf = json.load(fp)
            boards[chip].append({"board": board, "info": conf["board_information"]})

    print("\033[93m*", chip_arch, "* the avaliable cvitek EVB boards\033[0m")
    for chip, board_list in boards.items():
        if not board_list:
            continue

        jump = 0
        print("%8s - " % chip, end="")
        for board in board_list:
            jump = jump + 1
            if jump > 1:
                print(
                    "           ",
                    board["board"],
                    " [",
                    board["info"],
                    "]",
                    end="\n",
                    sep="",
                )
            else:
                print(board["board"], " [", board["info"], "]", end="\n", sep="")


def print_usage():
    chips = build_helper.get_chip_list()
    chip_list = list(itertools.chain(*chips.values()))

    # Initialize the dictionary
    map_name = dict()
    map_info = dict()
    for what in chip_list:
        map_name[what] = []

    for board_dir in sorted(os.listdir(build_helper.BOARD_DIR)):
        if board_dir.strip() == "default":
            continue
        board_dir = os.path.join(build_helper.BOARD_DIR, board_dir)
        if not os.path.isdir(board_dir):
            continue
        m = re.search(
            r"^([0-9a-z]+)_(.+)$", os.path.basename(board_dir), flags=re.IGNORECASE
        )
        chip, br_name = m.groups()
        map_name[chip].append(br_name)
        cj_path = os.path.join(board_dir, "config.json")
        with open(cj_path, "r", encoding="utf-8") as fp:
            cj = json.load(fp)
            map_info[chip + br_name] = cj["board_information"]

    print("\033[93m- The avaliable cvitek EVB boards\033[0m")
    for chip in sorted(map_name):
        jump = 0
        print("%8s - " % chip, end="")
        for boards in sorted(map_name[chip]):
            jump = jump + 1
            if jump > 1:
                print(
                    "           ",
                    chip,
                    "_",
                    boards,
                    " [",
                    map_info[chip + boards],
                    "]",
                    end="\n",
                    sep="",
                )
            else:
                print(
                    chip,
                    "_",
                    boards,
                    " [",
                    map_info[chip + boards],
                    "]",
                    end="\n",
                    sep="",
                )


config_list_tmpl = """
    configurations {{
        {config}
    }};
"""


fdt_list_tmpl = """
    {fdt}
"""


fdt_tmpl = """
        fdt-{chip}_{board} {{
            description = "cvitek device tree - {chip}_{board}";
            data = /incbin/("./{chip}_{board}.dtb");
            type = "flat_dt";
            arch = "arm64";
            compression = "none";
            hash-1 {{
                algo = "{hash_algo}";
            }};
        }};
"""


config_tmpl = """
        config-{chip}_{board} {{
            description = "boot cvitek system with board {chip}_{board}";
            kernel = "kernel-1";
            ramdisk = "ramdisk-1";
            fdt = "fdt-{chip}_{board}";
        }};
"""


config_noramdisk_tmpl = """
        config-{chip}_{board} {{
            description = "boot cvitek system with board {chip}_{board}";
            kernel = "kernel-1";
            fdt = "fdt-{chip}_{board}";
        }};
"""


def insertAfter(string, keyword, replacement):
    i = string.find(keyword)
    return string[: i + len(keyword)] + replacement + string[i + len(keyword) :]


def gen_single_board_its(chip, board, skip_ramdisk=False):
    its_str = {
        "fdt": "",
        "config": "",
    }

    os.makedirs(build_helper.BUILD_OUTPUT_DIR, exist_ok=True)
    its_path = os.path.join(build_helper.BUILD_OUTPUT_DIR, "multi.its.tmp")

    cfg_tmpl = config_noramdisk_tmpl if skip_ramdisk else config_tmpl
    its_str["fdt"] = fdt_tmpl.format(
        chip=chip, board=board, hash_algo=get_hash_algo(board)
    )
    its_str["config"] = cfg_tmpl.format(chip=chip, board=board)

    config_list = config_list_tmpl.format(**its_str)
    fdt_list = fdt_list_tmpl.format(**its_str)

    with open(its_path, "r") as fp:
        FileString = fp.read()
        replaceTmp = insertAfter(FileString, "/*FDT*/", fdt_list)
        replaceDone = insertAfter(replaceTmp, "/*CFG*/", config_list)

    with open(its_path, "w") as fp:
        fp.write(replaceDone)


def get_hash_algo(br_name):
    if "fpga" in br_name:
        return "crc32"
    elif "palladium" in br_name:
        return "crc32"
    return "sha256"


def gen_board_its(input_arch, skip_ramdisk=False):
    its_str = {
        "fdt": "",
        "config": "",
    }
    os.makedirs(build_helper.BUILD_OUTPUT_DIR, exist_ok=True)
    its_path = os.path.join(build_helper.BUILD_OUTPUT_DIR, "multi.its.tmp")

    board_list = []

    for _arch in build_helper.get_chip_list():
        _dir = os.path.join(build_helper.BOARD_DIR, _arch)

        for board_dir in sorted(os.listdir(_dir)):
            if board_dir.strip() == "default":
                continue
            board_dir = os.path.join(build_helper.BOARD_DIR, _arch, board_dir)
            if not os.path.isdir(board_dir):
                continue

            chip_arch, chip, br_name = board_dir_to_name(board_dir)
            if chip_arch == input_arch:
                board_list.append(Arch(chip, br_name))

    cfg_tmpl = config_noramdisk_tmpl if skip_ramdisk else config_tmpl
    its_str["fdt"] = "\n".join(
        fdt_tmpl.format(chip=chip, board=board, hash_algo=get_hash_algo(board))
        for chip, board in board_list
    )
    its_str["config"] = "\n".join(
        cfg_tmpl.format(chip=chip, board=board) for chip, board in board_list
    )

    config_list = config_list_tmpl.format(**its_str)
    fdt_list = fdt_list_tmpl.format(**its_str)

    with open(its_path, "r") as fp:
        FileString = fp.read()
        replaceTmp = insertAfter(FileString, "/*FDT*/", fdt_list)
        replaceDone = insertAfter(replaceTmp, "/*CFG*/", config_list)

    with open(its_path, "w") as fp:
        fp.write(replaceDone)


def main():
    args = parse_args()

    # build_helper.init_logging(args.logfile, stdout_level=args.verbose)
    # build_helper.dump_debug_info()
    logging.debug("[%s] start", datetime.now().isoformat())

    # The location of the top Kconfig
    os.environ["srctree"] = build_helper.BUILD_REPO_DIR

    if args.gen_build_kconfig:
        gen_build_kconfig()

    if args.scan_boards_config:
        boards = scan_boards_config()
        gen_build_env(boards)

    if args.gen_board_env:
        gen_board_env(args.gen_board_env)

    if args.print_usage:
        print_usage()

    if args.list_chip_arch:
        list_chip_arch()

    if args.list_boards:
        list_boards_by_chip_arch(args.list_boards)

    if args.arch:
        gen_board_its(args.arch.lower(), args.skip_ramdisk)

    if args.get_chip_arch:
        get_chip_arch(args.board_name)

    if args.gen_single_board_its:
        gen_single_board_its(
            args.chip_name.lower(), args.board_name.lower(), args.skip_ramdisk
        )

    logging.debug("[%s] finished", datetime.now().isoformat())


if __name__ == "__main__":
    main()
