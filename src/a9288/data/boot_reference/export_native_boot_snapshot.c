#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gam4980_core.h"

typedef struct native_boot_header {
    uint8_t magic[8];
    uint32_t version;
    uint32_t ram_size;
    uint32_t pc;
    uint32_t regs;
    uint32_t status;
    uint32_t bank_count;
    uint16_t banks[16];
} native_boot_header_t;

static int load_exact(const char *path, uint8_t *data, size_t size)
{
    FILE *file = fopen(path, "rb");
    int ok;

    if (!file)
        return 0;
    ok = fread(data, 1, size, file) == size && fgetc(file) == EOF;
    fclose(file);
    return ok;
}

static int load_game(const char *path, uint8_t *header, uint32_t *size_out)
{
    FILE *file = fopen(path, "rb");
    long size;

    if (!file)
        return 0;
    if (fseek(file, 0, SEEK_END) != 0 ||
        (size = ftell(file)) < (long)GAM4980_GAME_HEADER_SIZE ||
        size > (long)GAM4980_GAME_MAX_SIZE ||
        fseek(file, 0, SEEK_SET) != 0 ||
        fread(header, 1, GAM4980_GAME_HEADER_SIZE, file) !=
            GAM4980_GAME_HEADER_SIZE ||
        fseek(file, 0, SEEK_SET) != 0 ||
        fread(gam4980_game_storage(), 1, (size_t)size, file) != (size_t)size) {
        fclose(file);
        return 0;
    }
    fclose(file);
    *size_out = (uint32_t)size;
    return 1;
}

int main(int argc, char **argv)
{
    gam4980_buffers_t buffers;
    native_boot_header_t snapshot;
    uint8_t game_header[GAM4980_GAME_HEADER_SIZE];
    uint8_t *ram = 0;
    uint8_t *flash = 0;
    uint8_t *rom8 = 0;
    uint8_t *rome = 0;
    uint32_t game_size = 0;
    uint32_t data;
    FILE *output = 0;
    int ok = 0;

    if (argc != 5) {
        fprintf(stderr, "usage: export_native_boot_snapshot 8.BIN E.BIN game.gam output.bin\n");
        return 2;
    }
    memset(&buffers, 0, sizeof(buffers));
    ram = (uint8_t *)malloc(GAM4980_RAM_SIZE);
    flash = (uint8_t *)malloc(GAM4980_FLASH_SIZE);
    rom8 = (uint8_t *)malloc(GAM4980_ROM_SIZE);
    rome = (uint8_t *)malloc(GAM4980_ROM_SIZE);
    if (!ram || !flash || !rom8 || !rome)
        goto done;
    if (!load_exact(argv[1], rom8, GAM4980_ROM_SIZE) ||
        !load_exact(argv[2], rome, GAM4980_ROM_SIZE))
        goto done;
    buffers.ram = ram;
    buffers.flash = flash;
    buffers.flash_size = GAM4980_FLASH_SIZE;
    buffers.rom_8 = rom8;
    buffers.rom_e = rome;
    if (gam4980_init(&buffers) <= 0 ||
        !load_game(argv[3], game_header, &game_size) ||
        gam4980_load_game_header(game_header, game_size) <= 0)
        goto done;

    memset(&snapshot, 0, sizeof(snapshot));
    memcpy(snapshot.magic, "C65BOOT", 7);
    snapshot.version = 2;
    snapshot.ram_size = GAM4980_RAM_SIZE;
    snapshot.pc = gam4980_debug_cpu_pc();
    snapshot.regs = gam4980_debug_cpu_regs();
    snapshot.status = gam4980_debug_cpu_status();
    snapshot.bank_count = 16;
    data = (uint32_t)game_header[0x42] |
        (uint32_t)game_header[0x43] << 8 |
        (uint32_t)game_header[0x44] << 16 |
        (uint32_t)game_header[0x45] << 24;
    snapshot.banks[5] = 0x020d;
    snapshot.banks[6] = 0x020e;
    snapshot.banks[7] = 0x020f;
    snapshot.banks[8] = 0x0210;
    snapshot.banks[9] = (uint16_t)(0x020d + (data >> 12));
    snapshot.banks[10] = (uint16_t)(snapshot.banks[9] + 1u);
    snapshot.banks[11] = (uint16_t)(snapshot.banks[9] + 2u);
    snapshot.banks[12] = (uint16_t)(snapshot.banks[9] + 3u);
    for (data = 0; data < 16u; ++data)
        snapshot.banks[data] = (uint16_t)gam4980_debug_bank(data);
    /* Page 3 is a read-only firmware parameter page, NOT physical RAM.
       Resource offsets, LCD aliases and font bases are read through it. */
    for (data = 0x300u; data < 0x400u; ++data)
        ram[data] = (uint8_t)gam4980_debug_read8(data);

    output = fopen(argv[4], "wb");
    if (!output ||
        fwrite(&snapshot, 1, sizeof(snapshot), output) != sizeof(snapshot) ||
        fwrite(ram, 1, GAM4980_RAM_SIZE, output) != GAM4980_RAM_SIZE)
        goto done;
    ok = 1;

done:
    if (output)
        fclose(output);
    free(rome);
    free(rom8);
    free(flash);
    free(ram);
    return ok ? 0 : 1;
}
