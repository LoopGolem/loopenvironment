/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <errno.h>
#include <endian.h>
#include <poll.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>

/* wlr-screencopy-unstable-v1, version 2: SHM and copy_with_damage. */
static const struct wl_interface frame_interface;
static const struct wl_interface *capture_types[] = { &frame_interface, NULL, &wl_output_interface };
static const struct wl_interface *copy_types[] = { &wl_buffer_interface };
static const struct wl_message manager_requests[] = {
    { "capture_output", "nio", capture_types },
    { "capture_output_region", "nioiiii", NULL },
    { "destroy", "", NULL },
};
static const struct wl_message frame_requests[] = {
    { "copy", "o", copy_types }, { "destroy", "", NULL },
    { "copy_with_damage", "2o", copy_types },
};
static const struct wl_message frame_events[] = {
    { "buffer", "uuuu", NULL }, { "flags", "u", NULL },
    { "ready", "uuu", NULL }, { "failed", "", NULL }, { "damage", "2uuuu", NULL },
};
static const struct wl_interface manager_interface = {
    "zwlr_screencopy_manager_v1", 2, 3, manager_requests, 0, NULL,
};
static const struct wl_interface frame_interface = {
    "zwlr_screencopy_frame_v1", 2, 3, frame_requests, 5, frame_events,
};

enum { WIDTH = 800, HEIGHT = 600, STRIDE = WIDTH * 4, FRAME_SIZE = STRIDE * HEIGHT };

struct capture {
    struct wl_output *output;
    struct wl_shm *shm;
    struct wl_proxy *manager;
    struct wl_buffer *buffer;
    uint8_t *pixels;
    uint32_t stride, format;
    unsigned outputs;
    uint32_t output_id, flags;
    uint64_t number, captured_at;
    struct wl_callback *heartbeat;
    int status;
};

static void global(void *data, struct wl_registry *registry, uint32_t id, const char *name,
                   uint32_t version) {
    struct capture *s = data;
    if (!strcmp(name, "wl_output")) {
        if (++s->outputs == 1) {
            s->output = wl_registry_bind(registry, id, &wl_output_interface, 1);
            s->output_id = id;
        } else
            s->status = -1;
    } else if (!strcmp(name, "wl_shm")) {
        s->shm = wl_registry_bind(registry, id, &wl_shm_interface, 1);
    } else if (!strcmp(name, manager_interface.name) && version >= 2) {
        s->manager = wl_registry_bind(registry, id, &manager_interface, 2);
    }
}

static void removed(void *data, struct wl_registry *registry, uint32_t id) {
    (void)registry;
    struct capture *s = data;
    if (id == s->output_id)
        s->status = -1;
}

static void format(void *data, struct wl_proxy *frame, uint32_t kind, uint32_t width,
                   uint32_t height, uint32_t stride) {
    struct capture *s = data;
    if (width != WIDTH || height != HEIGHT || stride < STRIDE || stride > 2 * STRIDE ||
        (kind != WL_SHM_FORMAT_XRGB8888 && kind != WL_SHM_FORMAT_ARGB8888)) {
        s->status = -1;
        return;
    }
    if (!s->buffer) {
        int fd = memfd_create("loopbridge-screencopy", MFD_CLOEXEC);
        int size = (int)stride * HEIGHT;
        if (fd < 0) {
            s->status = -1;
            return;
        }
        s->pixels = ftruncate(fd, size) == 0
            ? mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0) : MAP_FAILED;
        if (s->pixels != MAP_FAILED) {
            struct wl_shm_pool *pool = wl_shm_create_pool(s->shm, fd, size);
            s->buffer = wl_shm_pool_create_buffer(pool, 0, WIDTH, HEIGHT, stride, kind);
            wl_shm_pool_destroy(pool);
        }
        close(fd);
        s->stride = stride;
        s->format = kind;
    }
    if (!s->buffer || s->stride != stride || s->format != kind) {
        s->status = -1;
        return;
    }
    wl_proxy_marshal_flags(frame, s->number ? 2 : 0, NULL, 2, 0, s->buffer);
}

static void flags(void *data, struct wl_proxy *frame, uint32_t value) {
    (void)frame;
    ((struct capture *)data)->flags = value;
}

static uint64_t monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static void ready(void *data, struct wl_proxy *frame, uint32_t hi, uint32_t lo, uint32_t ns) {
    (void)frame; (void)hi; (void)lo; (void)ns;
    struct capture *s = data;
    s->captured_at = monotonic_ns();
    s->status = 1;
}

static void failed(void *data, struct wl_proxy *frame) {
    (void)frame;
    ((struct capture *)data)->status = -1;
}

static void damage(void *data, struct wl_proxy *frame, uint32_t x, uint32_t y,
                   uint32_t width, uint32_t height) {
    (void)data; (void)frame; (void)x; (void)y; (void)width; (void)height;
}

static int write_all(const void *data, size_t remaining) {
    const uint8_t *next = data;
    while (remaining) {
        ssize_t bytes = write(STDOUT_FILENO, next, remaining);
        if (bytes < 0 && errno == EINTR)
            continue;
        if (bytes <= 0)
            return -1;
        next += bytes;
        remaining -= bytes;
    }
    return 0;
}

static int header(uint8_t kind, uint64_t sequence, uint64_t stamp) {
    uint8_t bytes[17] = {kind};
    sequence = htobe64(sequence);
    stamp = htobe64(stamp);
    memcpy(bytes + 1, &sequence, sizeof sequence);
    memcpy(bytes + 9, &stamp, sizeof stamp);
    return write_all(bytes, sizeof bytes);
}

static void heartbeat(void *data, struct wl_callback *callback, uint32_t serial) {
    (void)serial;
    struct capture *s = data;
    wl_callback_destroy(callback);
    s->heartbeat = NULL;
    if (!s->status && header(2, s->number, monotonic_ns()) < 0)
        s->status = -1;
}

static int stream(struct wl_display *display, struct capture *s) {
    static void (*callbacks[])(void) = {
        (void (*)(void))format, (void (*)(void))flags,
        (void (*)(void))ready, (void (*)(void))failed, (void (*)(void))damage,
    };
    static const struct wl_callback_listener heartbeat_listener = {heartbeat};
    struct pollfd peer = { .fd = wl_display_get_fd(display), .events = POLLIN };
    while (s->outputs == 1) {
        s->status = 0;
        struct wl_proxy *frame = wl_proxy_marshal_flags(s->manager, 0, &frame_interface,
                                                         2, 0, NULL, 0, s->output);
        wl_proxy_add_listener(frame, callbacks, s);
        uint64_t next_check = monotonic_ns() + 1000000000;
        while (!s->status) {
            while (wl_display_prepare_read(display) != 0) {
                if (wl_display_dispatch_pending(display) < 0)
                    return 1;
            }
            if (s->status) {
                wl_display_cancel_read(display);
                break;
            }
            if (wl_display_flush(display) < 0) {
                wl_display_cancel_read(display);
                return 1;
            }
            int result = poll(&peer, 1, 1000);
            if (result > 0 && (peer.revents & POLLIN)) {
                if (wl_display_read_events(display) < 0 || wl_display_dispatch_pending(display) < 0)
                    return 1;
            } else {
                wl_display_cancel_read(display);
                if (result < 0 && errno == EINTR)
                    continue;
                if (result != 0)
                    return 1;
            }
            if (!s->status && !s->heartbeat && monotonic_ns() >= next_check) {
                /* A round trip distinguishes a static output from a stalled compositor. */
                s->heartbeat = wl_display_sync(display);
                wl_callback_add_listener(s->heartbeat, &heartbeat_listener, s);
                next_check = monotonic_ns() + 1000000000;
            }
        }
        wl_proxy_marshal_flags(frame, 1, NULL, 2, WL_MARSHAL_FLAG_DESTROY);
        if (s->status < 0 || s->flags > 1 || header(1, ++s->number, s->captured_at) < 0)
            return 1;
        if (!s->flags && s->stride == STRIDE) {
            if (write_all(s->pixels, FRAME_SIZE) < 0)
                return 1;
        } else {
            for (unsigned y = 0; y < HEIGHT; y++) {
                unsigned row = s->flags ? HEIGHT - y - 1 : y;
                if (write_all(s->pixels + row * s->stride, STRIDE) < 0)
                    return 1;
            }
        }
    }
    return 1;
}

int main(void) {
    if (prctl(PR_SET_DUMPABLE, 0L, 0L, 0L, 0L) < 0)
        return 1;
    const char *dir = getenv("XDG_RUNTIME_DIR");
    const char *name = getenv("WAYLAND_DISPLAY");
    if (!dir || strcmp(dir, "/private/run") || !name || strncmp(name, "wayland-", 8)
        || strchr(name, '/') || getenv("WAYLAND_SOCKET") || __BYTE_ORDER != __LITTLE_ENDIAN)
        return 1;

    struct wl_display *display = wl_display_connect(NULL);
    if (!display)
        return 1;
    struct capture capture = {0};
    struct wl_registry *registry = wl_display_get_registry(display);
    const struct wl_registry_listener listener = {global, removed};
    wl_registry_add_listener(registry, &listener, &capture);
    int result = 1;
    if (wl_display_roundtrip(display) >= 0 && capture.outputs == 1 && capture.shm && capture.manager)
        result = stream(display, &capture);
    wl_display_disconnect(display);
    return result;
}
