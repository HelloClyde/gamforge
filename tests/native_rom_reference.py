"""PC-only A firmware reference for native adapter equivalence tests."""

from py65.devices.mpu65c02 import MPU

from a9288.compiler.boot import DEFAULT_ROME


class FirmwareMemory:
    def __init__(self, bank):
        self.rom = DEFAULT_ROME.read_bytes()
        self.ram = bytearray(65536)
        self.bank = bank

    def __getitem__(self, address):
        if 0x5000 <= address < 0x9000:
            return self.rom[0xA0000 + self.bank * 0x4000 + address - 0x5000]
        if address >= 0xD000:
            return self.rom[0xA8000 + address - 0xD000]
        return self.ram[0x1000 if address == 0x400 else address]

    def __setitem__(self, address, value):
        self.ram[0x1000 if address == 0x400 else address] = value


def invoke_firmware(memory, pc, a, arguments):
    cpu = MPU(memory=memory)
    memory.ram[0x28:0x2A] = (0x1800).to_bytes(2, "little")
    memory.ram[0x1800 : 0x1800 + len(arguments)] = arguments
    cpu.pc = pc
    cpu.a = a
    cpu.sp = 0xFD
    cpu.p = 0x30
    memory.ram[0x1FE:0x200] = b"\xff\x1f"
    for _ in range(500000):
        if cpu.pc == 0x2000:
            return cpu
        # The runtime's three fixed bank services are not drawing helpers.
        if cpu.pc in (0xE8F8, 0xE8FB, 0xE8FE):
            if cpu.pc == 0xE8F8:
                cpu.a = memory.bank
            else:
                memory.bank = cpu.a
            cpu.pc = (cpu.stPopWord() + 1) & 65535
        else:
            cpu.step()
    raise AssertionError(f"ROM call did not return: bank={memory.bank} PC={cpu.pc:04x}")


def trace_rom_message_box(text, timeout, *, key_after=None, timer_before=5):
    """Run the original bank-9 message-box control/layout code.

    Only its external drawing/allocator/input APIs are substituted. Arithmetic,
    wrapping, argument construction, timeout loop and timer save/restore are
    the actual E.BIN instructions, not a second copy of the native algorithm.
    """
    memory = FirmwareMemory(9)
    cpu = MPU(memory=memory)
    ram = memory.ram
    ram[0x28:0x2A] = (0x1800).to_bytes(2, "little")
    ram[0x2A:0x2C] = (0x2400).to_bytes(2, "little")
    ram[0x1800:0x1804] = b"\x00\x26" + timeout.to_bytes(2, "little")
    ram[0x2600 : 0x2600 + len(text) + 1] = text + b"\0"
    cpu.pc = 0x8A7C
    cpu.sp = 0xFD
    cpu.p = 0x30
    ram[0x1FE:0x200] = b"\xff\x1f"
    calls, messages = [], 0
    timer = timer_before

    def word(address):
        return ram[address] | ram[address + 1] << 8

    def string(address):
        data = bytearray()
        while ram[address]:
            data.append(ram[address])
            address += 1
        return bytes(data)

    def ret8(value):
        cpu.a = value & 255
        cpu.FlagsNZ(cpu.a)

    def ret16(value):
        ram[0x20:0x22] = value.to_bytes(2, "little")
        ret8(value >> 8)

    names = {
        0xE71E: "strlen",
        0xE874: "size",
        0xE947: "alloc",
        0xE877: "save",
        0xE85D: "clear",
        0xE72D: "strncpy",
        0xE79A: "text",
        0xE797: "rect",
        0xE87D: "fill",
        0xE935: "getmsg",
        0xE7B2: "timer_open",
        0xE7B5: "timer_close",
        0xE7B8: "timer_get",
        0xE87A: "restore",
        0xE94A: "free",
    }
    for _ in range(3000000):
        if cpu.pc == 0x2000:
            return dict(calls=calls, result=cpu.a, messages=messages, timer=timer)
        if cpu.pc != 0xD2F6:
            cpu.step()
            continue
        table, sp = word(0x26), word(0x28)
        name = names[table]
        if name == "strlen":
            ret16(len(string(word(sp))))
        elif name == "strncpy":
            dest, source, count = word(sp), word(sp + 2), word(sp + 4)
            ram[dest : dest + count] = ram[source : source + count]
            ret16(dest)
        elif name in ("size", "save", "restore", "clear", "rect", "fill"):
            args = [cpu.a, *ram[sp : sp + 3]]
            calls.append((name, args))
            if name == "size":
                size = ((args[2] >> 3) - (args[0] >> 3) + 1) * (args[3] - args[1] + 1)
                dest = word(sp + 3)
                ram[dest : dest + 2] = size.to_bytes(2, "little")
        elif name == "text":
            calls.append((name, [cpu.a, ram[sp], string(word(sp + 1)).hex()]))
        elif name == "alloc":
            ret16(0x3000)
        elif name == "free":
            ret8(1)
        elif name == "timer_get":
            ret8(timer)
        elif name == "timer_close":
            timer = 0
            calls.append((name, []))
        elif name == "timer_open":
            timer = cpu.a
            calls.append((name, [timer]))
        elif name == "getmsg":
            messages += 1
            kind = 1 if key_after is not None and messages >= key_after else 6
            dest = word(sp)
            ram[dest : dest + 3] = bytes((kind, 0x2F, 0))
            ret8(1)
        else:
            raise AssertionError(name)
        cpu.pc = (cpu.stPopWord() + 1) & 65535
    raise AssertionError(f"message box did not return: PC={cpu.pc:04x}")


def trace_rom_query_box(text, selection=0, info_type=0, keys=(0x2F,), *, alloc_ok=True):
    """Execute the real bank-9 GuiQueryBox, mocking only external services."""
    memory = FirmwareMemory(9)
    cpu = MPU(memory=memory)
    ram = memory.ram
    ram[0x28:0x2A] = (0x1800).to_bytes(2, "little")
    ram[0x2A:0x2C] = (0x2400).to_bytes(2, "little")
    ram[0x1800:0x1803] = bytes((info_type, 0, 0x26))
    ram[0x2600 : 0x2600 + len(text) + 1] = text + b"\0"
    cpu.pc = 0x7540
    cpu.a = selection
    cpu.sp = 0xFD
    cpu.p = 0x30
    ram[0x1FE:0x200] = b"\xff\x1f"
    calls, messages = [], 0

    def word(address):
        return memory[address] | memory[(address + 1) & 65535] << 8

    def string(address):
        data = bytearray()
        for _ in range(512):
            value = memory[address]
            address = (address + 1) & 65535
            if not value:
                return bytes(data)
            data.append(value)
        raise AssertionError("unterminated ROM string")

    def ret8(value):
        cpu.a = value & 255
        cpu.FlagsNZ(cpu.a)

    def ret16(value):
        ram[0x20:0x22] = value.to_bytes(2, "little")
        ret8(value >> 8)

    names = {
        0xE71E: "strlen",
        0xE874: "size",
        0xE947: "alloc",
        0xE877: "save",
        0xE85D: "clear",
        0xE72D: "strncpy",
        0xE79A: "text",
        0xE797: "rect",
        0xE87D: "fill",
        0xE860: "reverse",
        0xE935: "getmsg",
        0xE87A: "restore",
        0xE94A: "free",
        0xE965: "kbd_get",
        0xE968: "kbd_set",
        0xE938: "filter",
        0xE93B: "kbd_type",
        0xE93E: "translate",
        0xE78E: "picture",
    }
    for _ in range(3000000):
        if cpu.pc == 0x2000:
            return dict(calls=calls, result=cpu.a, messages=messages)
        if cpu.pc != 0xD2F6:
            cpu.step()
            continue
        table, sp = word(0x26), word(0x28)
        if table not in names:
            raise AssertionError(
                f"unknown query API {table:04x} A={cpu.a:02x} stack={ram[sp : sp + 20].hex()} calls={calls}"
            )
        name = names[table]
        if name == "strlen":
            ret16(len(string(word(sp))))
        elif name == "strncpy":
            dest, source, count = word(sp), word(sp + 2), word(sp + 4)
            for i in range(count):
                ram[dest + i] = memory[source + i]
            ret16(dest)
        elif name in ("size", "save", "restore", "clear", "rect", "fill", "reverse"):
            args = [cpu.a, *ram[sp : sp + 3]]
            calls.append((name, args))
            if name == "size":
                size = ((args[2] >> 3) - (args[0] >> 3) + 1) * (args[3] - args[1] + 1)
                dest = word(sp + 3)
                ram[dest : dest + 2] = size.to_bytes(2, "little")
        elif name == "text":
            calls.append((name, [cpu.a, ram[sp], string(word(sp + 1)).hex()]))
        elif name == "picture":
            width = ram[sp + 1] - cpu.a + 1
            height = ram[sp + 2] - ram[sp] + 1
            pointer = word(sp + 3)
            count = ((width + 7) // 8) * height
            calls.append(
                (
                    name,
                    [
                        cpu.a,
                        *ram[sp : sp + 3],
                        pointer,
                        ram[sp + 5],
                        bytes(memory[pointer + i] for i in range(count)).hex(),
                    ],
                )
            )
        elif name == "alloc":
            ret16(0x3000 if alloc_ok else 0)
        elif name == "free":
            ret8(1)
        elif name == "kbd_get":
            ret16(0x1234)
        elif name == "kbd_set":
            calls.append((name, [word(sp)]))
            ret8(1)
        elif name in ("filter", "kbd_type"):
            calls.append((name, [cpu.a]))
            ret8(1)
        elif name == "translate":
            dest = word(sp)
            key = ram[dest + 1]
            translations = {
                0: 4,
                1: 7,
                2: 1,
                3: 2,
                6: 5,
                7: 3,
                0x2E: 0x28,
                0x2F: 0x27,
                0x35: 0x22,
                0x37: 0x24,
                0x38: 0x23,
                0x39: 0x25,
                0x3A: 0x20,
                0x3B: 0x21,
            }
            if key in (0x15, 0x26):  # Y/N, WM_CHAR_ASC
                ram[dest : dest + 3] = bytes((2, ord("y" if key == 0x15 else "n"), 0))
            else:
                ram[dest : dest + 3] = bytes((5, translations.get(key, 0), 0))
            ret8(1)
        elif name == "getmsg":
            if messages >= len(keys):
                raise AssertionError(f"query needs more keys: {calls}")
            dest = word(sp)
            ram[dest : dest + 3] = bytes((1, keys[messages], 0))
            messages += 1
            ret8(1)
        cpu.pc = (cpu.stPopWord() + 1) & 65535
    raise AssertionError(f"query did not return: PC={cpu.pc:04x}")
