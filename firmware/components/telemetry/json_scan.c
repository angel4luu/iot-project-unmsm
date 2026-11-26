#include "json_scan.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

static bool is_space(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

const char *json_value_of(const char *json, size_t len, const char *key) {
    const size_t klen = strlen(key);
    for (size_t i = 0; i + klen + 2 < len; i++) {
        if (json[i] == '"' && memcmp(json + i + 1, key, klen) == 0 && json[i + 1 + klen] == '"') {
            size_t j = i + klen + 2;
            while (j < len && is_space(json[j])) {
                j++;
            }
            if (j < len && json[j] == ':') {
                j++;
                while (j < len && is_space(json[j])) {
                    j++;
                }
                return j < len ? json + j : NULL;
            }
        }
    }
    return NULL;
}

bool json_string_of(const char *json, size_t len, const char *key, char *out, size_t cap,
                    bool *is_null) {
    const char *v = json_value_of(json, len, key);
    const char *end = json + len;
    if (is_null != NULL) {
        *is_null = false;
    }
    if (v == NULL || cap == 0) {
        return false;
    }
    if (is_null != NULL && end - v >= 4 && memcmp(v, "null", 4) == 0) {
        *is_null = true;
        out[0] = '\0';
        return true;
    }
    if (*v != '"') {
        return false;
    }
    size_t n = 0;
    for (const char *p = v + 1; p < end; p++) {
        if (*p == '"') {
            out[n] = '\0';
            return true;
        }
        if (*p == '\\' || n + 1 >= cap) {
            return false;
        }
        out[n++] = *p;
    }
    return false;
}

// Copies the number token at `v` into `buf` (NUL-terminated); false when there is none
// or it does not end at a delimiter inside the range.
static bool number_token(const char *v, const char *end, char *buf, size_t cap) {
    size_t n = 0;
    while (v + n < end && strchr("+-0123456789.eE", v[n]) != NULL && v[n] != '\0') {
        if (n + 1 >= cap) {
            return false;
        }
        buf[n] = v[n];
        n++;
    }
    buf[n] = '\0';
    if (n == 0 || v + n >= end) {
        return false; // truncated: a number is never the last byte of an object
    }
    const char d = v[n];
    return d == ',' || d == '}' || is_space(d);
}

bool json_number_of(const char *json, size_t len, const char *key, double *out) {
    const char *v = json_value_of(json, len, key);
    char buf[40];
    if (v == NULL || !number_token(v, json + len, buf, sizeof buf)) {
        return false;
    }
    char *stop = NULL;
    const double x = strtod(buf, &stop);
    if (stop == buf || *stop != '\0' || !isfinite(x)) {
        return false;
    }
    *out = x;
    return true;
}

bool json_uint_of(const char *json, size_t len, const char *key, uint64_t max, uint64_t *out) {
    const char *v = json_value_of(json, len, key);
    char buf[24];
    if (v == NULL || !number_token(v, json + len, buf, sizeof buf)) {
        return false;
    }
    uint64_t x = 0;
    for (const char *p = buf; *p; p++) {
        if (*p < '0' || *p > '9' || x > (max - (uint64_t)(*p - '0')) / 10u) {
            return false;
        }
        x = x * 10u + (uint64_t)(*p - '0');
    }
    *out = x;
    return true;
}

bool json_bool_of(const char *json, size_t len, const char *key, bool *out) {
    const char *v = json_value_of(json, len, key);
    const char *end = json + len;
    if (v == NULL) {
        return false;
    }
    if (end - v > 4 && memcmp(v, "true", 4) == 0) {
        *out = true;
        return true;
    }
    if (end - v > 5 && memcmp(v, "false", 5) == 0) {
        *out = false;
        return true;
    }
    return false;
}
