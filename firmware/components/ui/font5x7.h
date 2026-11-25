// Minimal 5x7 column font (space, digits, A-Z, "-", ":", ".") for the OLED (from bring-up stage 2).
#pragma once

#include <stdint.h>

// Returns 5 column bytes (bit 0 = top row); unknown characters render as space.
const uint8_t *font5x7_glyph(char c);
