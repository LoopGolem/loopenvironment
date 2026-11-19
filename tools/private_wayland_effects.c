/* SPDX-License-Identifier: Apache-2.0
 * Minimal version-1 protocol bindings for disposable private Sway.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>

static const struct wl_interface capture_frame;
static const struct wl_interface pointer;
static const struct wl_interface *capture_types[] = { &capture_frame, NULL, &wl_output_interface };
static const struct wl_interface *buffer_types[] = { &wl_buffer_interface };
static const struct wl_interface *pointer_types[] = { &wl_seat_interface, &pointer };

static const struct wl_message capture_manager_requests[] = {
    { "capture_output", "nio", capture_types },
    { "capture_output_region", "nioiiii", NULL },
    { "destroy", "", NULL },
};
static const struct wl_message frame_requests[] = {
    { "copy", "o", buffer_types }, { "destroy", "", NULL },
};
static const struct wl_message frame_events[] = {
    { "buffer", "uuuu", NULL }, { "flags", "u", NULL },
    { "ready", "uuu", NULL }, { "failed", "", NULL },
};
static const struct wl_interface capture_manager = {
    "zwlr_screencopy_manager_v1", 1, 3, capture_manager_requests, 0, NULL,
};
static const struct wl_interface capture_frame = {
    "zwlr_screencopy_frame_v1", 1, 2, frame_requests, 4, frame_events,
};
static const struct wl_message pointer_manager_requests[] = {
    { "create_virtual_pointer", "?on", pointer_types }, { "destroy", "", NULL },
};
static const struct wl_message pointer_requests[] = {
    { "motion", "uff", NULL }, { "motion_absolute", "uuuuu", NULL },
    { "button", "uuu", NULL }, { "axis", "uuf", NULL },
    { "frame", "", NULL }, { "axis_source", "u", NULL }, { "axis_stop", "uu", NULL },
    { "axis_discrete", "uufi", NULL }, { "destroy", "", NULL },
};
static const struct wl_interface pointer_manager = {
    "zwlr_virtual_pointer_manager_v1", 1, 2, pointer_manager_requests, 0, NULL,
};
static const struct wl_interface pointer = {
    "zwlr_virtual_pointer_v1", 1, 9, pointer_requests, 0, NULL,
};

static const struct wl_interface keyboard;
static const struct wl_interface *keyboard_types[] = { &wl_seat_interface, &keyboard };
static const struct wl_message keyboard_manager_requests[] = {
    { "create_virtual_keyboard", "on", keyboard_types },
};
static const struct wl_message keyboard_requests[] = {
    { "keymap", "uhu", NULL }, { "key", "uuu", NULL },
    { "modifiers", "uuuu", NULL }, { "destroy", "", NULL },
};
static const struct wl_interface keyboard_manager = {
    "zwp_virtual_keyboard_manager_v1", 1, 1, keyboard_manager_requests, 0, NULL,
};
static const struct wl_interface keyboard = {
    "zwp_virtual_keyboard_v1", 1, 4, keyboard_requests, 0, NULL,
};

struct state {
    struct wl_output *output;
    struct wl_shm *shm;
    struct wl_proxy *capture;
    struct wl_proxy *input;
    struct wl_proxy *keys;
    struct wl_seat *seat;
    unsigned seats;
    unsigned outputs;
    uint32_t width, height, stride, flags;
    unsigned char *pixels;
    size_t size;
    struct wl_buffer *buffer;
    int status;
};

static void global(void *opaque, struct wl_registry *registry, uint32_t id,
                   const char *name, uint32_t version) {
    (void)version;
    struct state *s = opaque;
    if (strcmp(name, "wl_output") == 0) {
        s->outputs++;
        if (s->outputs == 1)
            s->output = wl_registry_bind(registry, id, &wl_output_interface, 1);
    } else if (strcmp(name, "wl_shm") == 0)
        s->shm = wl_registry_bind(registry, id, &wl_shm_interface, 1);
    else if (strcmp(name, capture_manager.name) == 0)
        s->capture = wl_registry_bind(registry, id, &capture_manager, 1);
    else if (strcmp(name, pointer_manager.name) == 0)
        s->input = wl_registry_bind(registry, id, &pointer_manager, 1);
    else if (strcmp(name, keyboard_manager.name) == 0)
        s->keys = wl_registry_bind(registry, id, &keyboard_manager, 1);
    else if (strcmp(name, "wl_seat") == 0 && ++s->seats == 1)
        s->seat = wl_registry_bind(registry, id, &wl_seat_interface, 1);
}

static void removed(void *opaque, struct wl_registry *registry, uint32_t id) {
    (void)opaque; (void)registry; (void)id;
}

static void format(void *opaque, struct wl_proxy *frame, uint32_t kind,
                   uint32_t width, uint32_t height, uint32_t stride) {
    struct state *s = opaque;
    if ((kind != WL_SHM_FORMAT_XRGB8888 && kind != WL_SHM_FORMAT_ARGB8888) ||
        width == 0 || height == 0 || width > 2048 || height > 2048 ||
        stride < width * 4 || stride > width * 8) {
        s->status = -1;
        return;
    }
    int fd = memfd_create("loopbridge-private-frame", MFD_CLOEXEC);
    s->size = (size_t)stride * height;
    if (fd < 0 || ftruncate(fd, (off_t)s->size) < 0) {
        if (fd >= 0) close(fd);
        s->status = -1;
        return;
    }
    s->pixels = mmap(NULL, s->size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (s->pixels == MAP_FAILED) {
        close(fd);
        s->pixels = NULL;
        s->status = -1;
        return;
    }
    struct wl_shm_pool *pool = wl_shm_create_pool(s->shm, fd, (int)s->size);
    s->buffer = wl_shm_pool_create_buffer(pool, 0, width, height, stride, kind);
    wl_shm_pool_destroy(pool);
    close(fd);
    s->width = width;
    s->height = height;
    s->stride = stride;
    wl_proxy_marshal_flags(frame, 0, NULL, 1, 0, s->buffer);
}

static void flags(void *opaque, struct wl_proxy *frame, uint32_t value) {
    (void)frame;
    ((struct state *)opaque)->flags = value;
}

static void ready(void *opaque, struct wl_proxy *frame, uint32_t hi, uint32_t lo, uint32_t nsec) {
    (void)frame; (void)hi; (void)lo; (void)nsec;
    ((struct state *)opaque)->status = 1;
}

static void failed(void *opaque, struct wl_proxy *frame) {
    (void)frame;
    ((struct state *)opaque)->status = -1;
}

static int capture(struct wl_display *display, struct state *s, int raw) {
    if (!s->capture || !s->shm)
        return 2;
    struct wl_proxy *frame = wl_proxy_marshal_flags(s->capture, 0, &capture_frame, 1, 0,
                                                    NULL, 0, s->output);
    void (*callbacks[])(void) = {
        (void (*)(void))format, (void (*)(void))flags,
        (void (*)(void))ready, (void (*)(void))failed,
    };
    wl_proxy_add_listener(frame, callbacks, s);
    while (!s->status)
        if (wl_display_dispatch(display) < 0)
            return 3;
    if (s->status < 0 || !s->pixels)
        return 3;
    if (raw) {
        if (s->width != 800 || s->height != 600 || s->flags > 1)
            return 3;
        for (unsigned y = 0; y < 180; y++) {
            unsigned source_y = y * 600 / 180;
            if (s->flags & 1)
                source_y = 599 - source_y;
            for (unsigned x = 0; x < 240; x++) {
                uint32_t pixel;
                memcpy(&pixel, s->pixels + source_y * s->stride + x * 800 / 240 * 4, 4);
                if (putchar((pixel >> 16) & 255) == EOF || putchar((pixel >> 8) & 255) == EOF ||
                    putchar(pixel & 255) == EOF)
                    return 3;
            }
        }
        return fflush(stdout) == 0 ? 0 : 3;
    }
    int distinct = 0;
    uint32_t first;
    memcpy(&first, s->pixels, 4);
    for (uint32_t y = 0; y < s->height && !distinct; y++)
        for (uint32_t x = 0; x < s->width; x++) {
            uint32_t pixel;
            memcpy(&pixel, s->pixels + y * s->stride + x * 4, 4);
            if ((pixel & 0xFFFFFF) != (first & 0xFFFFFF)) {
                distinct = 1;
                break;
            }
        }
    printf("{\"width\":%u,\"height\":%u,\"bytes\":%zu,\"distinctPixels\":%s}\n",
           s->width, s->height, s->size, distinct ? "true" : "false");
    wl_buffer_destroy(s->buffer);
    wl_proxy_marshal_flags(frame, 1, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
    munmap(s->pixels, s->size);
    return distinct ? 0 : 3;
}

static uint32_t monotonic_ms(void) {
    struct timespec clock;
    clock_gettime(CLOCK_MONOTONIC, &clock);
    return (uint32_t)((uint64_t)clock.tv_sec * 1000 + clock.tv_nsec / 1000000);
}

static int point(struct wl_display *display, struct state *s, unsigned x, unsigned y, int click) {
    if (!s->input)
        return 2;
    struct wl_proxy *device = wl_proxy_marshal_flags(s->input, 0, &pointer, 1, 0, NULL, NULL);
    if (wl_display_roundtrip(display) < 0)
        return 3;
    usleep(250000);
    wl_proxy_marshal_flags(device, 1, NULL, 1, 0, monotonic_ms(), x, y, 800u, 600u);
    wl_proxy_marshal_flags(device, 4, NULL, 1, 0);
    if (wl_display_roundtrip(display) < 0)
        return 3;
    if (!click)
        return 0;
    usleep(250000);
    wl_proxy_marshal_flags(device, 2, NULL, 1, 0, monotonic_ms(), 0x110u, 1u);
    wl_proxy_marshal_flags(device, 4, NULL, 1, 0);
    if (wl_display_roundtrip(display) < 0)
        return 3;
    usleep(100000);
    wl_proxy_marshal_flags(device, 2, NULL, 1, 0, monotonic_ms(), 0x110u, 0u);
    wl_proxy_marshal_flags(device, 4, NULL, 1, 0);
    int result = wl_display_roundtrip(display);
    usleep(250000);
    wl_proxy_marshal_flags(device, 8, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
    return result < 0 ? 3 : 0;
}

struct stroke {
    uint32_t key;
    uint32_t modifiers;
};

static int stroke_for(struct xkb_keymap *map, xkb_keysym_t symbol,
                      uint32_t shift, struct stroke *result) {
    for (unsigned level = 0; level <= 1; level++) {
        for (xkb_keycode_t code = 8; code <= xkb_keymap_max_keycode(map); code++) {
            const xkb_keysym_t *values = NULL;
            int count = xkb_keymap_key_get_syms_by_level(map, code, 0, level, &values);
            if (count == 1 && values[0] == symbol) {
                *result = (struct stroke){code - 8, level ? shift : 0};
                return 1;
            }
        }
    }
    return 0;
}

static int send_keys(struct wl_display *display, struct state *s, const char *name) {
    if (!s->keys || !s->seat || s->seats != 1)
        return 2;
    xkb_keysym_t symbols[121];
    size_t count = 0;
    if (name) {
        const char *keys[] = {"Return", "Tab", "Escape", "BackSpace", "Delete",
                              "Up", "Down", "Left", "Right", "space"};
        for (size_t i = 0; i < sizeof keys / sizeof *keys; i++)
            if (!strcmp(name, keys[i])) {
                symbols[count++] = xkb_keysym_from_name(name, XKB_KEYSYM_NO_FLAGS);
                break;
            }
    } else {
        int byte;
        while ((byte = getchar()) != EOF) {
            if (count >= 120 || byte < 32 || byte > 126)
                return 1;
            symbols[count++] = xkb_utf32_to_keysym((uint32_t)byte);
        }
    }
    if (!count)
        return 1;

    struct xkb_context *ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    if (!ctx)
        return 3;
    struct xkb_rule_names rules = {.rules="evdev", .model="pc105", .layout="us"};
    struct xkb_keymap *map = xkb_keymap_new_from_names(ctx, &rules, XKB_KEYMAP_COMPILE_NO_FLAGS);
    if (!map) {
        xkb_context_unref(ctx);
        return 3;
    }
    int status = 3;
    struct stroke strokes[121];
    xkb_mod_index_t shift = xkb_keymap_mod_get_index(map, XKB_MOD_NAME_SHIFT);
    if (shift >= 32)
        goto done;
    for (size_t i = 0; i < count; i++)
        if (!stroke_for(map, symbols[i], 1u << shift, &strokes[i]))
            goto done;

    char *keymap = xkb_keymap_get_as_string(map, XKB_KEYMAP_FORMAT_TEXT_V1);
    int fd = memfd_create("loopbridge-keymap", MFD_CLOEXEC);
    size_t len = keymap ? strlen(keymap) + 1 : 0;
    if (fd < 0 || !len || write(fd, keymap, len) != (ssize_t)len) {
        if (fd >= 0) close(fd);
        free(keymap);
        goto done;
    }
    free(keymap);
    struct wl_proxy *device = wl_proxy_marshal_flags(s->keys, 0, &keyboard, 1, 0, s->seat, NULL);
    wl_proxy_marshal_flags(device, 0, NULL, 1, 0, 1u, fd, (uint32_t)len);
    close(fd);
    if (wl_display_roundtrip(display) < 0)
        goto done;
    for (size_t i = 0; i < count; i++) {
        wl_proxy_marshal_flags(device, 2, NULL, 1, 0, strokes[i].modifiers, 0u, 0u, 0u);
        wl_proxy_marshal_flags(device, 1, NULL, 1, 0, monotonic_ms(), strokes[i].key, 1u);
        wl_proxy_marshal_flags(device, 1, NULL, 1, 0, monotonic_ms(), strokes[i].key, 0u);
    }
    wl_proxy_marshal_flags(device, 2, NULL, 1, 0, 0u, 0u, 0u, 0u);
    if (wl_display_roundtrip(display) >= 0) {
        wl_proxy_marshal_flags(device, 3, NULL, 1, WL_MARSHAL_FLAG_DESTROY);
        status = 0;
    }
done:
    xkb_keymap_unref(map);
    xkb_context_unref(ctx);
    return status;
}

int main(int argc, char **argv) {
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    const char *display_name = getenv("WAYLAND_DISPLAY");
    if ((argc < 2 || argc > 4) || !runtime || strcmp(runtime, "/private/run") || !display_name ||
        strncmp(display_name, "wayland-", 8) || strchr(display_name, '/'))
        return 1;
    struct wl_display *display = wl_display_connect(NULL);
    if (!display)
        return 1;
    struct state state = {0};
    struct wl_registry *registry = wl_display_get_registry(display);
    const struct wl_registry_listener listener = {global, removed};
    wl_registry_add_listener(registry, &listener, &state);
    int result = wl_display_roundtrip(display);
    if (result >= 0 && state.outputs == 1) {
        if (argc == 2 && !strcmp(argv[1], "capture"))
            result = capture(display, &state, 0);
        else if (argc == 2 && !strcmp(argv[1], "frame"))
            result = capture(display, &state, 1);
        else if (argc == 2 && !strcmp(argv[1], "type"))
            result = send_keys(display, &state, NULL);
        else if (argc == 3 && !strcmp(argv[1], "key"))
            result = send_keys(display, &state, argv[2]);
        else if (argc == 2 && !strcmp(argv[1], "click"))
            result = point(display, &state, 400, 300, 1);
        else if (argc == 4 && (!strcmp(argv[1], "click") || !strcmp(argv[1], "move"))) {
            char *end_x, *end_y;
            unsigned long x = strtoul(argv[2], &end_x, 10);
            unsigned long y = strtoul(argv[3], &end_y, 10);
            result = (*argv[2] && *argv[3] && !*end_x && !*end_y && x < 800 && y < 600)
                ? point(display, &state, (unsigned)x, (unsigned)y, !strcmp(argv[1], "click")) : 1;
        }
        else
            result = 1;
    } else {
        result = 1;
    }
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return result;
}
