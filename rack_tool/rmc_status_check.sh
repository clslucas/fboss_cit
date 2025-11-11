#!/bin/bash
# Usage: ./rmc_status_check.sh [BUS] [ADDR]
# Defaults: BUS=10, ADDR=0x23

# --- Color Definitions ---
COLOR_GREEN='\033[0;32m'
COLOR_RED='\033[0;31m'
COLOR_YELLOW='\033[1;33m'
COLOR_NC='\033[0m' # No Color

# 1. Validate inputs and dependencies
if ! command -v i2cdump &> /dev/null; then
    echo -e "${COLOR_RED}Error: 'i2cdump' command not found. Please install i2c-tools.${COLOR_NC}" >&2
    exit 1
fi

BUS="${1:-10}"
ADDR="${2:-0x23}"

# 2. Read data from the I2C device
I2C_OUTPUT=$(i2cdump -y "$BUS" "$ADDR" 2>&1)
if [ $? -ne 0 ]; then
    echo -e "${COLOR_RED}Error reading from I2C device bus $BUS at address $ADDR.${COLOR_NC}" >&2
    echo "Details: $I2C_OUTPUT" >&2
    exit 1
fi

# 3. Pipe data to awk for processing and colored output
echo "$I2C_OUTPUT" | awk '
BEGIN{
  IGNORECASE=1  # accept hex in either case

  # Color codes for awk
  C_GREEN = "\033[0;32m"
  C_RED   = "\033[0;31m"
  C_YELLOW= "\033[1;33m"
  C_NC    = "\033[0m"

  # Register 0x0
  MAP["0x00 7"]="wRPU_READY_PLD_R 1"  # AALC1 RPU READY
  MAP["0x00 6"]="wRPU_READY_SPARE_PLD_R 1"  # AALC1 RPU READY SPARE
  MAP["0x00 5"]="wRPU_2_READY_PLD_R 1"  # AALC2 RPU READY
  MAP["0x00 4"]="wRPU_2_READY_SPARE_PLD_R 1"  # AALC2 RPU READY SPARE
  MAP["0x00 3"]="IT_STOP_PUMP 0"  # AALC2 STOP PUMP
  MAP["0x00 2"]="IT_STOP_PUMP_SPARE 0"  # AALC1 STOP PUMP SPARE
  MAP["0x00 1"]="IT_STOP_PUMP_2 0"  # AALC2 STOP PUMP
  MAP["0x00 0"]="IT_STOP_PUMP_SPARE_2 0"  # AALC2 STOP PUMP SPARE
  # Register 0x1
  MAP["0x01 7"]="wP24V_SM_INA230_ALERT_N_R 1"  # 24V power monitor for flow meter
  MAP["0x01 6"]="wP24V_AUX_INA230_ALERT_N_R 1"  # 24V power monitor for valve(M12) 
  MAP["0x01 5"]="wP48V_HSC_ALERT_N 1"  # HSC alert
  MAP["0x01 4"]="wSMB_TMC75_TEMP_ALERT_N_R 1"  # temp sensor alert
  MAP["0x01 3"]="wPWRGD_P52V_HSC_PWROK_R 1"  # 52V power good
  MAP["0x01 2"]="wPWRGD_P24V_AUX_R 1"  # 24V(valve) power good
  MAP["0x01 1"]="wPWRGD_P12V_AUX_R 1"  # 12V BRICK power good
  MAP["0x01 0"]="wPWRGD_P12V_SCM_R 1"  # 12V SCM power good
  # Register 0x2
  MAP["0x02 7"]="wPWRGD_P5V_AUX_R 1"              # 5V power good
  MAP["0x02 6"]="wPWRGD_P3V3_AUX_R 1"             # 3.3V power good
  MAP["0x02 5"]="wPWRGD_P1V5_AUX_R 1"             # 1.5V power good
  MAP["0x02 4"]="wPWRGD_P1V05_AUX_R 1"            # 1.05V power good
  MAP["0x02 3"]="wPWRGD_P24V_SMPWROK 1"           # 24V (meter)power good
  MAP["0x02 2"]="wPWRGD_COMPUTE_BLADE_BUF_R[0] 0"  # tray1 power good
  MAP["0x02 1"]="wPWRGD_COMPUTE_BLADE_BUF_R[1] 0"  # tray2 power good
  MAP["0x02 0"]="wPWRGD_COMPUTE_BLADE_BUF_R[2] 0"  # tray3 power good
  # Register 0x3
  MAP["0x03 7"]="wPWRGD_COMPUTE_BLADE_BUF_R[3] 0"    # tray4 power good
  MAP["0x03 6"]="wPWRGD_COMPUTE_BLADE_BUF_R[4] 0"    # tray5 power good
  MAP["0x03 5"]="wPWRGD_COMPUTE_BLADE_BUF_R[6] 0"    # tray6 power good
  MAP["0x03 4"]="wPWRGD_COMPUTE_BLADE_BUF_R[6] 0"    # tray7 power good
  MAP["0x03 3"]="wPWRGD_COMPUTE_BLADE_BUF_R[7] 0"    # tray8 power good
  MAP["0x03 2"]="wPWRGD_COMPUTE_BLADE_BUF_R[8] 0"    # tray9 power good
  MAP["0x03 1"]="wPWRGD_COMPUTE_BLADE_BUF_R[9] 0"    # tray10 power good
  MAP["0x03 0"]="wPWRGD_COMPUTE_BLADE_BUF_R[10] 0"   # tray20 power good
  # Register 0x4
  MAP["0x04 7"]="wPWRGD_COMPUTE_BLADE_BUF_R[11] 0"     # tray21 power good
  MAP["0x04 6"]="wPWRGD_COMPUTE_BLADE_BUF_R[12] 0"     # tray22 power good
  MAP["0x04 5"]="wPWRGD_COMPUTE_BLADE_BUF_R[13] 0"     # tray23 power good
  MAP["0x04 4"]="wPWRGD_COMPUTE_BLADE_BUF_R[14] 0"     # tray24 power good
  MAP["0x04 3"]="wPWRGD_COMPUTE_BLADE_BUF_R[15] 0"     # tray25 power good
  MAP["0x04 2"]="wPWRGD_COMPUTE_BLADE_BUF_R[16] 0"     # tray26 power good
  MAP["0x04 1"]="wPWRGD_COMPUTE_BLADE_BUF_R[17] 0"     # tray27 power good
  MAP["0x04 0"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[0] 0"  # tray11 power good
  # Register 0x5
  MAP["0x05 7"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[1] 0"  # tray12 power good
  MAP["0x05 6"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[2] 0"  # tray13 power good
  MAP["0x05 5"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[3] 0"  # tray14 power good
  MAP["0x05 4"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[4] 0"  # tray15 power good
  MAP["0x05 3"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[5] 0"  # tray16 power good
  MAP["0x05 2"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[6] 0"  # tray17 power good
  MAP["0x05 1"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[7] 0"  # tray18 power good
  MAP["0x05 0"]="wPWRGD_NVS_BLADE_PWROK_L_BUF_R[8] 0"  # tray19 power good
  # Register 0x6
  MAP["0x06 7"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[0] 1"  # tray2 large leak
  MAP["0x06 6"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[1] 1"  # tray3 large leak
  MAP["0x06 5"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[2] 1"  # tray4 large leak
  MAP["0x06 4"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[3] 1"  # tray5 large leak
  MAP["0x06 3"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[4] 1"  # tray6 large leak
  MAP["0x06 2"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[5] 1"  # tray7 large leak
  MAP["0x06 1"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[6] 1"  # tray8 large leak
  MAP["0x06 0"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[7] 1"  # tray9 large leak
  # Register 0x7
  MAP["0x07 7"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[8] 1"  # tray9 large leak
  MAP["0x07 6"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[9] 1"  # tray10 large leak
  MAP["0x07 5"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[10] 1"  # tray20 large leak
  MAP["0x07 4"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[11] 1"  # tray21 large leak
  MAP["0x07 3"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[12] 1"  # tray22 large leak
  MAP["0x07 2"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[13] 1"  # tray23 large leak
  MAP["0x07 1"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[14] 1"  # tray24 large leak
  MAP["0x07 0"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[15] 1"  # tray25 large leak
  # Register 0x8
  MAP["0x08 7"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[16] 1"  # tray26 large leak
  MAP["0x08 6"]="wLEAK_DETECT_COMPUTE_BLADE_N_BUF_R[17] 1"  # tray27 large leak
  MAP["0x08 5"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[0] 1"  # tray11 large leak
  MAP["0x08 4"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[1] 1"  # tray12 large leak
  MAP["0x08 3"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[2] 1"  # tray13 large leak
  MAP["0x08 2"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[3] 1"  # tray14 large leak
  MAP["0x08 1"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[4] 1"  # tray15 large leak
  MAP["0x08 0"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[5] 1"  # tray16 large leak
  # Register 0x9
  MAP["0x09 7"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[6] 1"  # tray17 large leak
  MAP["0x09 6"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[7] 1"  # tray18 large leak
  MAP["0x09 5"]="wLEAK_DETECT_NVS_BLADE_N_BUF_R[8] 1"  # tray19 large leak
  MAP["0x09 4"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[9] 1"  # tray1 small leak
  MAP["0x09 3"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[10] 1"  # tray2 small leak
  MAP["0x09 2"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[11] 1"  # tray3 small leak
  MAP["0x09 1"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[12] 1"  # tray4 small leak
  MAP["0x09 0"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[13] 1"  # tray5 small leak
  # Register 0xA
  MAP["0x0A 7"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[5] 1"  # tray6 small leak
  MAP["0x0A 6"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[6] 1"  # tray7 small leak
  MAP["0x0A 5"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[7] 1"  # tray8 small leak
  MAP["0x0A 4"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[8] 1"  # tray9 small leak
  MAP["0x0A 3"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[9] 1"  # tray10 small leak
  MAP["0x0A 2"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[10] 1"  # tray20 small leak
  MAP["0x0A 1"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[11] 1"  # tray21 small leak
  MAP["0x0A 0"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[12] 1"  # tray22 small leak
  # Register 0xB
  MAP["0x0B 7"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[13] 1"  # tray23 small leak
  MAP["0x0B 6"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[14] 1"  # tray24 small leak
  MAP["0x0B 5"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[15] 1"  # tray25 small leak
  MAP["0x0B 4"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[16] 1"  # tray26 small leak
  MAP["0x0B 3"]="wRSVD_COMPUTE_BLADE_GPIO_BUF_R[17] 1"  # tray27 small leak
  MAP["0x0B 2"]="wRSVD_NVS_BLADE_GPIO_BUF_R[0] 1"  # tray11 small leak
  MAP["0x0B 1"]="wRSVD_NVS_BLADE_GPIO_BUF_R[1] 1"  # tray12 small leak
  MAP["0x0B 0"]="wRSVD_NVS_BLADE_GPIO_BUF_R[2] 1"  # tray13 small leak
  # Register 0xC
  MAP["0x0C 7"]="wRSVD_NVS_BLADE_GPIO_BUF_R[3] 1"  # tray14 small leak
  MAP["0x0C 6"]="wRSVD_NVS_BLADE_GPIO_BUF_R[4] 1"  # tray15 small leak
  MAP["0x0C 5"]="wRSVD_NVS_BLADE_GPIO_BUF_R[5] 1"  # tray16 small leak
  MAP["0x0C 4"]="wRSVD_NVS_BLADE_GPIO_BUF_R[6] 1"  # tray17 small leak
  MAP["0x0C 3"]="wRSVD_NVS_BLADE_GPIO_BUF_R[7] 1"  # tray18 small leak
  MAP["0x0C 2"]="wRSVD_NVS_BLADE_GPIO_BUF_R[8] 1"  # tray19 small leak
  MAP["0x0C 1"]="PWREN_COMPUTE_BLADE1_EN_R 0"   # tray1 enable
  MAP["0x0C 0"]="PWREN_COMPUTE_BLADE2_EN_R 0"   # tray2 enable
  # Register 0xD ===== yellow rows only =====
  MAP["0x0D 7"]="PWREN_COMPUTE_BLADE3_EN_R 0"   # tray3 enable
  MAP["0x0D 6"]="PWREN_COMPUTE_BLADE4_EN_R 0"   # tray4 enable
  MAP["0x0D 5"]="PWREN_COMPUTE_BLADE5_EN_R 0"   # tray5 enable
  MAP["0x0D 4"]="PWREN_COMPUTE_BLADE6_EN_R 0"   # tray6 enable
  MAP["0x0D 3"]="PWREN_COMPUTE_BLADE7_EN_R 0"   # tray7 enable
  MAP["0x0D 2"]="PWREN_COMPUTE_BLADE8_EN_R 0"   # tray8 enable
  MAP["0x0D 1"]="PWREN_COMPUTE_BLADE9_EN_R 0"   # tray9 enable
  MAP["0x0D 0"]="PWREN_COMPUTE_BLADE10_EN_R 0"  # tray10 enable
  # Register 0xE
  MAP["0x0E 7"]="PWREN_COMPUTE_BLADE11_EN_R 0"  # tray20 enable
  MAP["0x0E 6"]="PWREN_COMPUTE_BLADE12_EN_R 0"  # tray21 enable
  MAP["0x0E 5"]="PWREN_COMPUTE_BLADE13_EN_R 0"  # tray22 enable
  MAP["0x0E 4"]="PWREN_COMPUTE_BLADE14_EN_R 0"  # tray23 enable
  MAP["0x0E 3"]="PWREN_COMPUTE_BLADE15_EN_R 0"  # tray24 enable
  MAP["0x0E 2"]="PWREN_COMPUTE_BLADE16_EN_R 0"  # tray25 enable
  MAP["0x0E 1"]="PWREN_COMPUTE_BLADE17_EN_R 0"  # tray26 enable
  MAP["0x0E 0"]="PWREN_COMPUTE_BLADE18_EN_R 0"  # tray27 enable
  # Register 0xF
  # --- NEW: NVS blade enables + presence/leak/fan signals ---
  # 0x0F: NVS blade enables (note *_L_* names imply active-low intent)
  MAP["0x0F 7"]="PWREN_NVS_BLADE1_EN_L_R 0"   # NVS tray11 enable
  MAP["0x0F 6"]="PWREN_NVS_BLADE2_EN_L_R 0"   # NVS tray12 enable
  MAP["0x0F 5"]="PWREN_NVS_BLADE3_EN_L_R 0"   # NVS tray13 enable
  MAP["0x0F 4"]="PWREN_NVS_BLADE4_EN_L_R 0"   # NVS tray14 enable
  MAP["0x0F 3"]="PWREN_NVS_BLADE5_EN_L_R 0"   # NVS tray15 enable
  MAP["0x0F 2"]="PWREN_NVS_BLADE6_EN_L_R 0"   # NVS tray16 enable
  MAP["0x0F 1"]="PWREN_NVS_BLADE7_EN_L_R 0"   # NVS tray17 enable
  MAP["0x0F 0"]="PWREN_NVS_BLADE8_EN_L_R 0"   # NVS tray18 enable
  # 0x10: NVS9 enable + compute tray presence [0..6]
  MAP["0x10 7"]="PWREN_NVS_BLADE9_EN_L_R 0"   # NVS tray19 enable
  MAP["0x10 6"]="wPRSNT_COMPUTE_BLADE_N[0] 0"  # compute tray1 presence
  MAP["0x10 5"]="wPRSNT_COMPUTE_BLADE_N[1] 0"  # compute tray2 presence
  MAP["0x10 4"]="wPRSNT_COMPUTE_BLADE_N[2] 0"  # compute tray3 presence
  MAP["0x10 3"]="wPRSNT_COMPUTE_BLADE_N[3] 0"  # compute tray4 presence
  MAP["0x10 2"]="wPRSNT_COMPUTE_BLADE_N[4] 0"  # compute tray5 presence
  MAP["0x10 1"]="wPRSNT_COMPUTE_BLADE_N[5] 0"  # compute tray6 presence
  MAP["0x10 0"]="wPRSNT_COMPUTE_BLADE_N[6] 0"  # compute tray7 presence
  # 0x11: presence continued
  MAP["0x11 7"]="wPRSNT_COMPUTE_BLADE_N[7] 0"  # compute tray8 presence
  MAP["0x11 6"]="wPRSNT_COMPUTE_BLADE_N[8] 0"  # compute tray9 presence
  MAP["0x11 5"]="wPRSNT_COMPUTE_BLADE_N[9] 0"  # compute tray10 presence
  MAP["0x11 4"]="wPRSNT_COMPUTE_BLADE_N[10] 0"  # compute tray20 presence
  MAP["0x11 3"]="wPRSNT_COMPUTE_BLADE_N[11] 0"  # compute tray21 presence
  MAP["0x11 2"]="wPRSNT_COMPUTE_BLADE_N[12] 0"  # compute tray22 presence
  MAP["0x11 1"]="wPRSNT_COMPUTE_BLADE_N[13] 0"  # compute tray23 presence
  MAP["0x11 0"]="wPRSNT_COMPUTE_BLADE_N[14] 0"  # compute tray24 presence
  # 0x12: presence continued
  MAP["0x12 7"]="wPRSNT_COMPUTE_BLADE_N[15] 0"  # compute tray25 presence
  MAP["0x12 6"]="wPRSNT_COMPUTE_BLADE_N[16] 0"  # compute tray26 presence
  MAP["0x12 5"]="wPRSNT_COMPUTE_BLADE_N[17] 0"  # compute tray27 presence
  MAP["0x12 4"]="wPRSNT_NVS_BLADE_N[0] 0"      # NVS tray11 presence
  MAP["0x12 3"]="wPRSNT_NVS_BLADE_N[1] 0"      # NVS tray12 presence
  MAP["0x12 2"]="wPRSNT_NVS_BLADE_N[2] 0"      # NVS tray13 presence
  MAP["0x12 1"]="wPRSNT_NVS_BLADE_N[3] 0"      # NVS tray14 presence
  MAP["0x12 0"]="wPRSNT_NVS_BLADE_N[4] 0"      # NVS tray15 presence
  # 0x13: presence + AALC link presence/spares
  MAP["0x13 7"]="wPRSNT_NVS_BLADE_N[5] 0"               # NVS tray16 presence
  MAP["0x13 6"]="wPRSNT_NVS_BLADE_N[6] 0"               # NVS tray17 presence
  MAP["0x13 5"]="wPRSNT_NVS_BLADE_N[7] 0"               # NVS tray18 presence
  MAP["0x13 4"]="wPRSNT_NVS_BLADE_N[8] 0"               # NVS tray19 presence
  MAP["0x13 3"]="wIT_GEAR_RPU_LINK_PRSNT_N_R 0"         # AALC1 presence
  MAP["0x13 2"]="wIT_GEAR_RPU_LINK_PRSNT_SPARE_N_R 1"   # AALC1 presence spare
  MAP["0x13 1"]="wIT_GEAR_RPU_2_LINK_PRSNT_N_R 0"       # AALC2 presence
  MAP["0x13 0"]="wIT_GEAR_RPU_2_LINK_PRSNT_SPARE_N_R 1"  # AALC2 presence spare
  # 0x14: leak sensors (both low-active *_Q_N_R and high-active *_DETECT) + presence
  MAP["0x14 7"]="wCHASSIS0_LEAK_Q_N_R 1"        # leak sensor0 (low active)
  MAP["0x14 6"]="wCHASSIS1_LEAK_Q_N_R 1"        # leak sensor1 (low active)
  MAP["0x14 5"]="wCHASSIS2_LEAK_Q_N_R 1"        # leak sensor2 (low active)
  MAP["0x14 4"]="wLEAK0_DETECT 0"               # leak sensor0 (high active)
  MAP["0x14 3"]="wLEAK1_DETECT 0"               # leak sensor1 (high active)
  MAP["0x14 2"]="wLEAK2_DETECT 0"               # leak sensor2 (high active)
  MAP["0x14 1"]="wPRSNT_LEAK0_SENSOR_R_PLD_N 0"  # leak sensor0 presence
  MAP["0x14 0"]="wPRSNT_LEAK1_SENSOR_R_PLD_N 0"  # leak sensor1 presence
  # 0x15: leak/fan presence + more low/high active leak signals
  MAP["0x15 7"]="wPRSNT_LEAK2_SENSOR_R_PLD_N 0"  # leak sensor2 presence
  MAP["0x15 6"]="wPRSNT_FANBP_0_PWR_R_PLD_N 0"  # fan board 0 power cable presence
  MAP["0x15 5"]="wPRSNT_FANBP_0_SIG_R_PLD_N 0"  # fan board 0 signal cable presence
  MAP["0x15 4"]="wPRSNT_FANBP_1_PWR_R_PLD_N 0"  # fan board 1 power cable presence
  MAP["0x15 3"]="wPRSNT_FANBP_1_SIG_R_PLD_N 0"  # fan board 1 signal cable presence
  MAP["0x15 2"]="wCHASSIS3_LEAK_Q_N_R 1"        # leak sensor3 (low active)
  MAP["0x15 1"]="wCHASSIS4_LEAK_Q_N_R 1"        # leak sensor4 (low active)
  MAP["0x15 0"]="wLEAK3_DETECT 0"               # leak sensor3 (high active)
  # 0x16: final leak4 detect + sensor presence
  MAP["0x16 7"]="wLEAK4_DETECT 0"               # leak sensor4 (high active)
  MAP["0x16 6"]="wPRSNT_LEAK3_SENSOR_R_PLD_N 0"  # leak sensor3 presence
  MAP["0x16 5"]="wPRSNT_LEAK4_SENSOR_R_PLD_N 0"  # leak sensor4 presence
  MAP["0x16 0"]="wPWRGD_BLADE_PWROK_SINGLE_B_UF_R 1"  # any tray power good
}

# portable hex string to decimal conversion
function hex2dec(h,  i,c,d,v,rest) {
  v=0
  # strip leading "0x" or "0X"
  if (length(h)>=2 && substr(h,1,2) ~ /^0x$/) h=substr(h,3)
  for (i=1; i<=length(h); i++) {
    c = substr(h,i,1)
    if (c>="0" && c<="9")      d = c+0
    else {
      rest = index("ABCDEF", toupper(c))
      if (rest==0) return -1
      d = 9 + rest  # A..F -> 10..15
    }
    v = v*16 + d
  }
  return v
}
# extract bit b (0..7) without shifts
function bit(v,b) { return int(v / (2^b)) % 2 }
# parse i2cdump rows like: "0d: f0 ff ..."
/^[0-9A-Fa-f]{2}:/{
  base = hex2dec(substr($1, 1, 2))
  if (base < 0) next
  # columns 2..17 are the 16 bytes
  for (i=2; i<=17; i++) {
    bytehex = $i
    if (bytehex ~ /^[0-9A-Fa-f]{2}$/) {
      off = base + (i-2)
      BYTES[sprintf("0x%02X",off)] = hex2dec(bytehex)
    }
  }
  next
}
END{
  # stable ordered output
  for (o=0; o<=0xFF; o++){
    keyoff = sprintf("0x%02X",o)
    for (b=0; b<8; b++){
      k = keyoff " " b
      if (k in MAP){
        split(MAP[k], tmp, " ")
        name = tmp[1]; good = tmp[2]
        val = (keyoff in BYTES) ? bit(BYTES[keyoff], b) : "?"

        if (val == "?") {
          status = C_YELLOW "[  ??  ]" C_NC
        } else if (val == good) {
          status = C_GREEN "[  OK  ]" C_NC
        } else {
          status = C_RED   "[ FAIL ]" C_NC
        }
        printf("%s %-35s = %s (expected %s)\n", status, name, val, good)
      }
    }
  }
}'
