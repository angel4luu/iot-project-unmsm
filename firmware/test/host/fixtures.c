#include "fixtures.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static FILE *open_fixture(const char *file) {
    char path[512];
    snprintf(path, sizeof path, "%s/%s", FIXTURES_DIR, file);
    return fopen(path, "r");
}

bool fixture_load(const char *name, fixture_t *out) {
    memset(out, 0, sizeof *out);
    char file[128];
    snprintf(file, sizeof file, "%s.csv", name);
    FILE *fp = open_fixture(file);
    if (fp == NULL) {
        return false;
    }
    size_t cap = 4096;
    out->pair = malloc(cap * sizeof *out->pair);
    out->v_mv = malloc(cap * sizeof *out->v_mv);
    out->i_mv = malloc(cap * sizeof *out->i_mv);
    char line[1024];
    bool ok = out->pair && out->v_mv && out->i_mv;
    while (ok && fgets(line, sizeof line, fp)) {
        unsigned p, v, i;
        if (line[0] == '#' || strncmp(line, "pair,", 5) == 0) {
            continue;
        }
        if (sscanf(line, "%u,%u,%u", &p, &v, &i) != 3 || v > 0xFFFF || i > 0xFFFF) {
            ok = false;
            break;
        }
        if (out->count == cap) {
            cap *= 2;
            uint32_t *np = realloc(out->pair, cap * sizeof *np);
            if (np)
                out->pair = np;
            uint16_t *nv = realloc(out->v_mv, cap * sizeof *nv);
            if (nv)
                out->v_mv = nv;
            uint16_t *ni = realloc(out->i_mv, cap * sizeof *ni);
            if (ni)
                out->i_mv = ni;
            ok = np && nv && ni;
            if (!ok)
                break;
        }
        out->pair[out->count] = p;
        out->v_mv[out->count] = (uint16_t)v;
        out->i_mv[out->count] = (uint16_t)i;
        out->count++;
    }
    fclose(fp);
    if (!ok || out->count == 0) {
        fixture_free(out);
        return false;
    }
    return true;
}

void fixture_free(fixture_t *f) {
    free(f->pair);
    free(f->v_mv);
    free(f->i_mv);
    memset(f, 0, sizeof *f);
}

// Splits one CSV line in place into at most `max` fields; returns the count.
static int split(char *line, char **fields, int max) {
    int n = 0;
    line[strcspn(line, "\r\n")] = '\0';
    char *p = line;
    while (n < max) {
        fields[n++] = p;
        char *c = strchr(p, ',');
        if (c == NULL)
            break;
        *c = '\0';
        p = c + 1;
    }
    return n;
}

static double num(const char *s) {
    return *s ? strtod(s, NULL) : NAN;
}

static bool find_row(const char *name, char **fields, char *line, size_t len) {
    FILE *fp = open_fixture("expected.csv");
    if (fp == NULL) {
        return false;
    }
    bool found = false;
    while (!found && fgets(line, (int)len, fp)) {
        if (split(line, fields, 7) == 7 && strcmp(fields[0], name) == 0) {
            found = true;
        }
    }
    fclose(fp);
    return found;
}

bool fixture_expected(const char *name, fixture_expected_t *out) {
    char line[512];
    char *f[7];
    if (!find_row(name, f, line, sizeof line)) {
        return false;
    }
    memset(out, 0, sizeof *out);
    out->valid = strcmp(f[1], "1") == 0;
    snprintf(out->flags, sizeof out->flags, "%s", f[2]);
    out->v_rms_v = num(f[3]);
    out->i_rms_a = num(f[4]);
    out->active_power_w = num(f[5]);
    out->energy_wh = num(f[6]);
    return true;
}

bool fixture_tolerance(fixture_tolerance_t *out) {
    char line[512];
    char *f[7];
    const char *rows[2] = {"tolerance_rel", "tolerance_abs"};
    double *dst[2] = {out->rel, out->abs};
    for (int r = 0; r < 2; r++) {
        if (!find_row(rows[r], f, line, sizeof line)) {
            return false;
        }
        for (int q = 0; q < 4; q++) {
            dst[r][q] = num(f[3 + q]);
        }
    }
    return true;
}

bool fixture_within(double got, double want, double rel, double abs) {
    double tol = fmax(abs, rel * fabs(want));
    return fabs(got - want) <= tol;
}
