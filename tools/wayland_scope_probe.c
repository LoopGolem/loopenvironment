/* SPDX-License-Identifier: Apache-2.0 */
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>

static void add(void *ctx, struct wl_registry *r, uint32_t id, const char *iface, uint32_t version) {
    (void)ctx; (void)r; (void)id;
    if (strstr(iface, "capture") || strstr(iface, "screencopy") || strstr(iface, "toplevel") ||
        strstr(iface, "export_dmabuf") || strstr(iface, "virtual_pointer") ||
        strstr(iface, "virtual_keyboard") || strstr(iface, "input_method"))
        printf("%s %u\n", iface, version);
}
static void remove_global(void *ctx, struct wl_registry *r, uint32_t id) {
    (void)ctx; (void)r; (void)id;
}

int main(void) {
    const struct wl_registry_listener listener = {add, remove_global};
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 1;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &listener, NULL);
    int result = wl_display_roundtrip(display);
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return result < 0;
}
