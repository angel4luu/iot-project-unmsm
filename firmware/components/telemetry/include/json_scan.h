// Minimal reader for the small, flat JSON objects the node receives (measurement
// ACKs, threshold config). Values are located by `"key":` in a compact or spaced
// object; strings must not contain escapes (refused, never unescaped). Input is a
// byte range: MQTT payloads are not NUL-terminated.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Start of the value of `key`, or NULL.
const char *json_value_of(const char *json, size_t len, const char *key);
// Copies a string value; false if absent, not a string, escaped, or too long. With
// `is_null` non-NULL, a JSON null is accepted (empty output, *is_null = true).
bool json_string_of(const char *json, size_t len, const char *key, char *out, size_t cap,
                    bool *is_null);
// Finite JSON number.
bool json_number_of(const char *json, size_t len, const char *key, double *out);
// Non-negative integer without fraction or exponent, at most `max`.
bool json_uint_of(const char *json, size_t len, const char *key, uint64_t max, uint64_t *out);
bool json_bool_of(const char *json, size_t len, const char *key, bool *out);
