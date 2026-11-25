#include "fake_nvs.h"

#include <stdlib.h>
#include <string.h>

static fake_nvs_slot_t *find(fake_nvs_t *f, const char *key) {
    for (int i = 0; i < FAKE_NVS_SLOTS; i++) {
        if (f->slots[i].used && strcmp(f->slots[i].key, key) == 0) {
            return &f->slots[i];
        }
    }
    return NULL;
}

static nvs_port_err_t set_blob(void *ctx, const char *key, const void *data, size_t len) {
    fake_nvs_t *f = ctx;
    if (f->fail_set_after >= 0 && f->sets >= f->fail_set_after) {
        return NVS_PORT_ERROR;
    }
    f->sets++;
    if (strlen(key) >= sizeof f->slots[0].key) { // NVS keys are at most 15 characters
        return NVS_PORT_ERROR;
    }
    fake_nvs_slot_t *s = find(f, key);
    for (int i = 0; s == NULL && i < FAKE_NVS_SLOTS; i++) {
        if (!f->slots[i].used) {
            s = &f->slots[i];
        }
    }
    if (s == NULL) {
        return NVS_PORT_ERROR;
    }
    unsigned char *copy = malloc(len ? len : 1);
    if (copy == NULL) {
        return NVS_PORT_ERROR;
    }
    memcpy(copy, data, len);
    free(s->data);
    strcpy(s->key, key);
    s->data = copy;
    s->len = len;
    s->used = true;
    return NVS_PORT_OK;
}

static nvs_port_err_t get_blob(void *ctx, const char *key, void *buf, size_t *len) {
    fake_nvs_slot_t *s = find(ctx, key);
    if (s == NULL) {
        return NVS_PORT_NOT_FOUND;
    }
    if (s->len > *len) {
        *len = s->len;
        return NVS_PORT_TOO_LARGE;
    }
    memcpy(buf, s->data, s->len);
    *len = s->len;
    return NVS_PORT_OK;
}

static nvs_port_err_t erase_key(void *ctx, const char *key) {
    fake_nvs_slot_t *s = find(ctx, key);
    if (s == NULL) {
        return NVS_PORT_NOT_FOUND;
    }
    free(s->data);
    memset(s, 0, sizeof *s);
    return NVS_PORT_OK;
}

static nvs_port_err_t commit(void *ctx) {
    ((fake_nvs_t *)ctx)->commits++;
    return NVS_PORT_OK;
}

nvs_port_t fake_nvs_init(fake_nvs_t *f) {
    memset(f, 0, sizeof *f);
    f->fail_set_after = -1;
    return (nvs_port_t){set_blob, get_blob, erase_key, commit, f};
}

void fake_nvs_free(fake_nvs_t *f) {
    for (int i = 0; i < FAKE_NVS_SLOTS; i++) {
        free(f->slots[i].data);
    }
    memset(f, 0, sizeof *f);
}
