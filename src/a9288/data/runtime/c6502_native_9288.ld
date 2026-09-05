ENTRY(DL_AppMain)

SECTIONS
{
    __dp = 0x00000000;
    . = 0x02700000;
    .startup : { KEEP(*(.text.startup)) }
    ASSERT(SIZEOF(.startup) <= 0x100, "native startup exceeds 0x100 bytes")

    /* This gap is part of the 9288 SDK ABI, not spare external code space.
       0x02700100 is the load image for code whose run address is IRAM
       0x00000800.  Placing normal text there makes GUI firmware execute
       overwritten IRAM helpers during CreateMainWindow. */
    .iram 0x00000800 : AT(0x02700100)
    {
    }

    .text 0x02701800 : AT(0x02701800)
    {
        /* Keep the 9288-facing entry, callback and runtime close to the SDK
           startup.  The generated game module is deliberately linked after
           them: some firmware GUI paths retain application callbacks through
           compact internal descriptors, and the official applications keep
           those callbacks in the front portion of the KF2 as well. */
        *c6502_native_9288.o(.text .text.*)
        *c6502_native_runtime.o(.text .text.*)
        *gam4980_9288_runtime.o(.text .text.*)
        *c6502_native_bridges.o(.text .text.*)
        *(.text .text.*)
    }
    .rodata :
    {
        *(.rodata .rodata.*)
    }
    .data :
    {
        *(.data .data.*)
    }
    . = ALIGN(4);
    __bss_start = .;
    .bss (NOLOAD) :
    {
        *(.bss .bss.*)
        *(COMMON)
    }
    . = ALIGN(4);
    __bss_end = .;
    .noinit (NOLOAD) :
    {
        *(.noinit .noinit.*)
    }
    .payload_tail :
    {
        BYTE(0xff)
    }
    __payload_end = .;
    ASSERT(__payload_end <= 0x02800000,
           "native GAM payload exceeds the 9288 application RAM window")
}
