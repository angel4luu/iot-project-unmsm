# Bring-up apps (build guide stages 1–4)

Small standalone ESP-IDF projects used on the breadboard before the full
firmware. They share `firmware/main/board.h` and the components in
`firmware/components/`. Build and flash one with:

```bash
source ~/esp/esp-idf-v5.4.4/export.sh
idf.py -C firmware/bringup/stage1_board -p /dev/ttyUSB0 flash monitor
```

| App | Build guide stage | What it checks |
|---|---|---|
| `stage1_board` | 1, board alone | Boot, Wi-Fi join with provisioned credentials, RGB cycles red/green/blue |
| `stage2_peripherals` | 2, OLED, buzzer, LED | I²C scan, OLED test text, 200 ms beep through the 2N2222, each LED colour |
| `stage34_adc_logger` | 3–4, analog front end | GPIO4/GPIO5 continuous ADC at 8,000 conversions/s; mean/min/max in mV each second; `d` dumps one second as CSV |

`make firmware-build-bringup` compile-checks all three on the PC (no board).
