"""Build a standalone S1C33 differential probe against the existing C cases."""

import argparse
import subprocess
from pathlib import Path

from a9288.compiler.build import symbol_address
from a9288.compiler.fast_helpers import PURE, RMW, fast_helper
from a9288.paths import DATA

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--toolchain", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
HERE = args.output_dir.resolve()
HERE.mkdir(parents=True, exist_ok=True)
TC = args.toolchain.resolve() / "bin"
symbols = sorted(PURE | RMW)
asm = [
    ".text",
    ".globl probe_start",
    "probe_start:",
    "    call run_tests",
    ".globl probe_done",
    "probe_done:",
    "    jp probe_done",
]
for ident, symbol in enumerate(symbols, 1):
    body, complete = fast_helper(symbol, ident)
    asm += body
    if not complete:
        asm += ["    pushn %r3"] + symbol_address("r0", "fallback")
        asm += ["    ld.w %r1, 1", "    ld.w [%r0], %r1", "    popn %r3", "    ret"]
    asm += [f".globl invoke_{ident}", f"invoke_{ident}:", "    sub %sp, 64"]
    asm += [f"    ld.w [%sp+{i * 4}], %r{i}" for i in range(16)]
    asm += ["    ld.w %r3, %r6"]
    for i in range(16):
        if i != 3:
            asm += [f"    ext {i * 4}", f"    ld.w %r{i}, [%r3]"]
    asm += [
        "    ext 12",
        "    ld.w %r3, [%r3]",
        f"    call {symbol}",
        "    sub %sp, 4",
        "    ld.w [%sp+0], %r3",
        "    ld.w %r3, [%sp+32]",
    ]
    for i in range(16):
        if i != 3:
            asm += [f"    ext {i * 4}", f"    ld.w [%r3], %r{i}"]
    asm += [
        "    ld.w %r0, [%sp+0]",
        "    ext 12",
        "    ld.w [%r3], %r0",
        "    add %sp, 4",
    ]
    asm += [f"    ld.w %r{i}, [%sp+{i * 4}]" for i in range(16)]
    asm += ["    add %sp, 64", "    ret"]
(HERE / "probe.S").write_text("\n".join(asm), encoding="ascii")
runtime = (DATA / "runtime/c6502_native_runtime.c").read_text(encoding="utf-8")
nz = (
    "static void set_nz(c6502_u32 *r, c6502_u8 value)\n{"
    + runtime.split("static void set_nz(c6502_u32 *r, c6502_u8 value)\n{", 1)[1].split(
        "\nstatic c6502_u8 stack8", 1
    )[0]
)
cmp16 = (
    "static void runtime_compare16"
    + runtime.split("static void runtime_compare16", 1)[1].split("\nstatic void *native_target", 1)[
        0
    ]
)
cases = (
    "    case C6502_BRIDGE_c6502_sem_adc8:"
    + runtime.split("    case C6502_BRIDGE_c6502_sem_adc8:", 1)[1].split(
        "    case C6502_BRIDGE_c6502_sem_copy16:", 1
    )[0]
)
defs = "\n".join(
    f"#define C6502_BRIDGE_{s} {i}\nvoid invoke_{i}(unsigned *,unsigned *);"
    for i, s in enumerate(symbols, 1)
)
calls = ",".join("invoke_" + str(i) for i in range(1, len(symbols) + 1))
source = (
    r"""
typedef unsigned c6502_u32;typedef unsigned short c6502_u16;typedef unsigned char c6502_u8;
#define C6502_FLAG_N 128u
#define C6502_FLAG_Z 2u
#define C6502_FLAG_C 1u
#define C6502_FLAG_V 64u
#define C6502_NEEDS_c6502_sem_ror_m 1
unsigned char ram[32768],ref_ram[32768];
unsigned input[16],actual[16],expected[16];
volatile unsigned report[12],fallback;
static unsigned rng=0x19382849u;
static unsigned random32(void){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
static unsigned char guest_read(unsigned short a){return ref_ram[a];}
static void guest_write(unsigned short a,unsigned char v){ref_ram[a]=v;}
static unsigned short get16(unsigned a){return ref_ram[a]|((unsigned)ref_ram[a+1]<<8);}
static void semantic_put16(unsigned*r,unsigned a,unsigned short v){
 a&=255;if(a==0x28){r[10]=v;return;}ref_ram[a]=v;ref_ram[a+1]=v>>8;
}
"""
    + defs
    + "\n"
    + nz
    + cmp16
    + r"""
static void reference(unsigned*r,unsigned id){unsigned result,address,i;switch(id){
"""
    + cases
    + r"""
case C6502_BRIDGE_c6502_runtime_cmp_int:runtime_compare16(r,get16(0x20),get16(0x23));return;
}}
static void (*const invoke[])(unsigned*,unsigned*)={"""
    + calls
    + r"""};
static int is_rmw(unsigned id){return """
    + "||".join(f"id=={i}" for i, s in enumerate(symbols, 1) if s in RMW)
    + r""";}
static int safe(unsigned a){return a>=4&&a<0x4000&&!(a>=12&&a<=14)&&
 !(a>=0x300&&a<=0x1000)&&a!=0x21b&&a!=0x2028;}
static int check(unsigned id,unsigned a,unsigned b,unsigned p,unsigned z){
 unsigned i,addr=b&65535,mem=is_rmw(id)||id==C6502_BRIDGE_c6502_sem_store16_imm;
 for(i=0;i<16;i++)input[i]=random32();
 input[4]=a;input[12]=b;input[13]=a;input[9]=p;input[11]=z;input[14]=(unsigned)ram;
 if(is_rmw(id)&&addr<32768){ram[addr]=ref_ram[addr]=a;}
 if(id==C6502_BRIDGE_c6502_runtime_cmp_int){
  ram[0x20]=ref_ram[0x20]=a;ram[0x21]=ref_ram[0x21]=a>>8;
  ram[0x23]=ref_ram[0x23]=b;ram[0x24]=ref_ram[0x24]=b>>8;
 }
 for(i=0;i<16;i++)expected[i]=input[i];
 unsigned slow=is_rmw(id)&&!safe(addr);
 if(!slow)reference(expected,id);
 fallback=0;invoke[id-1](input,actual);
 report[1]++;
 if(fallback!=slow){report[2]=1;report[3]=id;report[4]=addr;return 0;}
 for(i=0;i<16;i++)if(actual[i]!=expected[i]){
  report[2]=2;report[3]=id;report[4]=i;report[5]=actual[i];report[6]=expected[i];
  report[7]=a;report[8]=b;report[9]=p;return 0;
 }
 if(mem){for(i=0;i<32768;i++)if(ram[i]!=ref_ram[i]){
  report[2]=3;report[3]=id;report[4]=i;report[5]=ram[i];report[6]=ref_ram[i];return 0;
 }}
 return 1;
}
void run_tests(void){unsigned i,j,c,id;
 for(i=0;i<12;i++)report[i]=0;
 for(i=0;i<32768;i++)ram[i]=ref_ram[i]=(i*29+17);
 for(i=0;i<65536;i++)for(c=0;c<2;c++){
  unsigned p=(random32()&~1u)|c;
  if(!check(C6502_BRIDGE_c6502_sem_adc8,i>>8,i&255,p,0))return;
  if(!check(C6502_BRIDGE_c6502_sem_sbc8,i>>8,i&255,p,0))return;
  if(!check(C6502_BRIDGE_c6502_sem_cmp8,i>>8,i&255,p,0))return;
 }
 for(i=0;i<512;i++)for(j=0;j<256;j++){
  if(!check(C6502_BRIDGE_c6502_sem_asl_a,i,0,j,0))return;
  if(!check(C6502_BRIDGE_c6502_sem_lsr_a,i,0,j,0))return;
 }
 for(i=0;i<65536;i++)if(!check(C6502_BRIDGE_c6502_runtime_cmp_int,i,random32(),random32(),0))return;
 for(i=0;i<256;i++)for(c=0;c<4;c++)
  if(!check(C6502_BRIDGE_c6502_sem_store16_imm,random32(),random32(),random32(),i|0xa1234500u))return;
 for(id=1;id<sizeof(invoke)/sizeof(invoke[0])+1;id++)if(is_rmw(id)){
  static const unsigned addresses[]={0,1,2,3,4,11,12,13,14,15,255,256,511,512,
   0x21a,0x21b,0x21c,0x2ff,0x300,0x3ff,0x400,0x401,0x1000,0x1001,0x2027,0x2028,0x2029,0x3fff,0x4000,0xffff};
  for(i=0;i<sizeof(addresses)/sizeof(addresses[0]);i++)for(c=0;c<16;c++)
   if(!check(id,(c*17),addresses[i]|0xa5000000u,random32(),0))return;
 }
 report[0]=0x50415353u;
}
"""
)
(HERE / "probe.c").write_text(source, encoding="ascii")
(HERE / "probe.ld").write_text(
    "ENTRY(probe_start)\nSECTIONS { . = 0x02700000; .text : { *(.text*) } .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }",
    encoding="ascii",
)
for ext in ("c", "S"):
    subprocess.run(
        [
            str(TC / "clang.exe"),
            "--target=s1c33-none-elf",
            "-O2",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-jump-tables",
            "-fomit-frame-pointer",
            "-c",
            str(HERE / f"probe.{ext}"),
            "-o",
            str(HERE / f"probe-{ext}.o"),
        ],
        check=True,
    )
subprocess.run(
    [
        str(TC / "ld.lld.exe"),
        "-T",
        str(HERE / "probe.ld"),
        str(HERE / "probe-c.o"),
        str(HERE / "probe-S.o"),
        "-o",
        str(HERE / "probe.elf"),
    ],
    check=True,
)
subprocess.run(
    [
        str(TC / "llvm-objcopy.exe"),
        "-O",
        "binary",
        str(HERE / "probe.elf"),
        str(HERE / "probe.bin"),
    ],
    check=True,
)
print("Probe helpers:", dict(enumerate(symbols, 1)))
