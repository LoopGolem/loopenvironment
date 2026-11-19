/* SPDX-License-Identifier: Apache-2.0
 * Minimal version-1 protocol bindings for the disposable private Sway probe.
 * No service endpoint calls this helper.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>

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

struct state {
    struct wl_output *output;
    struct wl_shm *shm;
    struct wl_proxy *capture;
    struct wl_proxy *input;
    unsigned outputs;
    uint32_t width, height, stride;
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
    char path[] = "/private/run/frame-XXXXXX";
    int fd = mkstemp(path);
    s->size = (size_t)stride * height;
    if (fd < 0 || unlink(path) < 0 || ftruncate(fd, (off_t)s->size) < 0) {
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
    (void)opaque; (void)frame; (void)value;
}

static void ready(void *opaque, struct wl_proxy *frame, uint32_t hi, uint32_t lo, uint32_t nsec) {
    (void)frame; (void)hi; (void)lo; (void)nsec;
    ((struct state *)opaque)->status = 1;
}

static void failed(void *opaque, struct wl_proxy *frame) {
    (void)frame;
    ((struct state *)opaque)->status = -1;
}

static int capture(struct wl_display *display, struct state *s) {
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

static int click(struct wl_display *display, struct state *s) {
    if (!s->input)
        return 2;
    struct wl_proxy *device = wl_proxy_marshal_flags(s->input, 0, &pointer, 1, 0, NULL, NULL);
    if (wl_display_roundtrip(display) < 0)
        return 3;
    usleep(250000);
    wl_proxy_marshal_flags(device, 1, NULL, 1, 0, monotonic_ms(), 400u, 300u, 800u, 600u);
    wl_proxy_marshal_flags(device, 4, NULL, 1, 0);
    if (wl_display_roundtrip(display) < 0)
        return 3;
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

int main(int argc, char **argv) {
    const char *runtime = getenv("XDG_RUNTIME_DIR");
    const char *display_name = getenv("WAYLAND_DISPLAY");
    if (argc != 2 || !runtime || strcmp(runtime, "/private/run") || !display_name ||
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
        if (!strcmp(argv[1], "capture"))
            result = capture(display, &state);
        else if (!strcmp(argv[1], "click"))
            result = click(display, &state);
        else
            result = 1;
    } else {
        result = 1;
    }
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return result;
}
