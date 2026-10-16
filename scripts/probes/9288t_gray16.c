/* Independent 9288T LCD depth probe. Never call GUI/FS while 4-bpp is active. */
#include "Dsys.h"
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned long u32;
/* Official Fumo uses these early entries without the later game-font +0x14
 * correction. In particular TextOutLen is +0x4f0, not +0x504. */
typedef char sdk_textout_slot[__builtin_offsetof(T_GUI_RelocationTable,TextOutLen)==0x4f0u?1:-1];
typedef char sdk_create_slot[__builtin_offsetof(T_GUI_RelocationTable,CreateMainWindow)==0x84u?1:-1];
typedef char sdk_cleanup_slot[__builtin_offsetof(T_GUI_RelocationTable,MainWindowCleanup)==0x17cu?1:-1];
#include "gray16_tables.h"

#define REG32(a) (*(volatile u32 *)(a))
#define REG16(a) (*(volatile u16 *)(a))
#define REG8(a) (*(volatile u8 *)(a))
#define MODE 0x00380200u
#define START 0x00380210u
#define LUT 0x00380400u
#define FB ((volatile u8 *)0x003c0000u)
#define LIMIT_TICKS 768u
#ifdef GRAY16_TRANSACTION_TEST
#define MAX_FRAMES 2u
#else
#define MAX_FRAMES 256u
#endif
static u32 saved_vram[4800], saved_lut[16], saved_mode;
static u16 saved_start;
static u8 source[1920];
static u32 frames[2], ticks[2], finished[2], restored, status;
static u32 psr_before, psr_after, dp_before, dp_after;
static int task_suspend_result, task_resume_result;
static u32 desktop[2400];
static u32 ui_phase,ui_ticks,ui_closed;
static T_GUI_HWND ui_window;
static u32 clock_previous;

static u32 clock_now(void)
{
    u32 n;
    volatile u8 *p = (volatile u8 *)0x40153u;
    for (n = 0; n < 4; ++n) {
        u8 d0=p[0], hi=p[5], lo=p[4], h=p[3], m=p[2], s=p[1], d=p[0];
        u32 t;
        if (d<d0 || s!=p[1] || m!=p[2] || h!=p[3] || lo!=p[4] || hi!=p[5]
            || s>=60u || m>=60u || h>=24u) continue;
        t=(((((u32)hi<<8)|lo)*86400u+h*3600u+m*60u+s)<<8)|d;
        if (clock_previous && ((t-clock_previous)&0x80000000u)) continue;
        clock_previous=t;
        return t;
    }
    return clock_previous;
}

static void make_source(u32 phase)
{
    u32 y,k;
    for(y=0;y<96;++y) for(k=0;k<20;++k)
        source[y*20+k]=(u8)((y*17u+k*31u+17u)^((phase&1u)?255u:0u));
}

/* A group maps 3 source bits on each of 2 rows to 3 destination pixels.
 * Tables have 4 vertical phases, 64 patterns: no runtime multiply/divide
 * and no per-pixel interpolation. The source's hidden 160th bit is ignored. */
#define DEFINE_RASTER(NAME, BITS, TABLE, STRIDE) \
void NAME(void) { \
    u32 dy; \
    for(dy=0;dy<144u;++dy) { \
        const u8 *a=source+yrow[dy]*20u, *b=source+ynext[dy]*20u; \
        const u16 *table=TABLE[yphase[dy]]; \
        volatile u8 *out=FB+(dy+8u)*STRIDE; \
        u32 g, bits=BITS, acc=table[((a[0]&128u)?7u:0u)|((b[0]&128u)?56u:0u)] >> (2u*BITS); \
        for(g=0;g<79u;++g) { \
            u32 byte=g>>2, shift=(g&3u)*2u; \
            u32 av=((u32)a[byte]<<8)|(byte<19u?a[byte+1u]:0u); \
            u32 bv=((u32)b[byte]<<8)|(byte<19u?b[byte+1u]:0u); \
            u32 pat=((av>>(13u-shift))&7u)|(((bv>>(13u-shift))&7u)<<3); \
            acc=(acc<<(3u*BITS))|table[pat]; bits+=3u*BITS; \
            while(bits>=8u) { bits-=8u; *out++=(u8)(acc>>bits); } \
        } \
        /* Last visible pixel clamps both horizontal neighbours to x=158. */ \
        { \
            u32 aa=(a[19]&2u)?7u:0u, bb=(b[19]&2u)?56u:0u; \
            u32 last=table[aa|bb]&((1u<<BITS)-1u); \
            acc=(acc<<(2u*BITS))|(last<<BITS)|((1u<<BITS)-1u); bits+=2u*BITS; \
            while(bits>=8u) { bits-=8u; *out++=(u8)(acc>>bits); } \
        } \
    } \
}
DEFINE_RASTER(raster4,2u,table4,60u)
DEFINE_RASTER(raster16,4u,table16,120u)

static void gradient(u32 depth)
{
    u32 x,y,stride=depth==4u?120u:60u;
    for(y=0;y<8u;++y) for(x=0;x<stride;++x) {
        if(depth==4u) {
            u32 a=(x*2u)/15u,b=(x*2u+1u)/15u;
            FB[y*stride+x]=(u8)((a<<4)|b);
        } else {
            u32 c=x/15u;
            FB[y*stride+x]=(u8)(c*85u);
        }
    }
    for(y=152u;y<160u;++y) for(x=0;x<stride;++x)FB[y*stride+x]=255u;
}

/* CPU-only entry, used without ROM by the build script. */
u32 cpu4(void) { make_source(0u); gradient(2u); raster4(); return 4u; }
u32 cpu16(void) { make_source(0u); gradient(4u); raster16(); return 16u; }

static u32 dma_idle(void)
{
    u32 i;
    for(i=0;i<4;++i) if(REG16(0x4822cu+i*16u)&1u)return 0;
    return 1;
}

static void restore_lcd(void)
{
    u32 i;
    REG32(MODE)=REG32(MODE)|(1u<<24); /* blank while restoring mode/pixels */
    for(i=0;i<4800u;++i)((volatile u32 *)FB)[i]=saved_vram[i];
    for(i=0;i<16u;++i)REG32(LUT+i*4u)=saved_lut[i];
    REG16(START)=saved_start;
    REG32(MODE)=saved_mode;
    restored=REG32(MODE)==saved_mode && REG16(START)==saved_start;
    for(i=0;i<4800u;++i)if(((volatile u32 *)FB)[i]!=saved_vram[i])restored=0;
    for(i=0;i<16u;++i)if(REG32(LUT+i*4u)!=saved_lut[i])restored=0;
}

/* A callable boundary is mandatory: restoring PSR overwrites flags. Inlining
 * once put the caller's suspend-result CMP before this write and its JRNE
 * afterwards, accidentally skipping rsm_tsk(3). Also declare the CC clobber. */
static __attribute__((noinline)) void run_probe(void)
{
    u32 psr,i,phase;
    __asm__ volatile("ld.w %0,%%psr":"=r"(psr));
    psr_before=psr;
    __asm__ volatile("ld.w %0,%%r15":"=r"(dp_before));
    { u32 off=psr&~16u; __asm__ volatile("ld.w %%psr,%0"::"r"(off):"cc","memory"); }
    /* Refuse to race an enabled DMA channel; never alter DMA configuration. */
    if(!dma_idle()) { status=2u; goto done; }
    saved_mode=REG32(MODE); saved_start=REG16(START);
    if((saved_mode&7u)!=1u) { status=3u; goto done; }
    if((REG16(0x380042u)&127u)!=29u || (REG16(0x38004cu)&1023u)!=159u) {
        status=4u; goto done;
    }
    for(i=0;i<4800u;++i)saved_vram[i]=((volatile u32 *)FB)[i];
    for(i=0;i<16u;++i)saved_lut[i]=REG32(LUT+i*4u);
    for(phase=0;phase<2u;++phase) {
        u32 begin,now,n;
        REG32(MODE)=saved_mode|(1u<<24);
        REG16(START)=0u;
        for(i=0;i<16u;++i) {
            u32 c=(i*63u+7u)/15u;
            if(!phase && i<4u)c=i*21u;
            REG32(LUT+i*4u)=(c<<2)|(c<<10)|(c<<18);
        }
        gradient(phase?4u:2u);
        make_source(0u); if(phase)raster16();else raster4();
        /* BPP encoding is log2(bits/pixel): 1=2bpp; 2=4bpp. Keep panel
           drive, timings, inversion and all unrelated mode bits unchanged. */
        REG32(MODE)=(saved_mode&~(7u|16u|(1u<<24)))|(phase?2u:1u);
        begin=clock_now(); now=begin;
        for(n=0;n<MAX_FRAMES;++n) {
            make_source(n); if(phase)raster16();else raster4();
            ++frames[phase]; now=clock_now();
            if(now-begin>=LIMIT_TICKS) { finished[phase]=1u; break; }
        }
        ticks[phase]=now-begin;
    }
    restore_lcd(); status=restored?1u:5u;
done:
    __asm__ volatile("ld.w %%psr,%0"::"r"(psr):"cc","memory");
    __asm__ volatile("ld.w %0,%%psr":"=r"(psr_after));
    __asm__ volatile("ld.w %0,%%r15":"=r"(dp_after));
}

#ifdef GRAY16_TRANSACTION_TEST
u32 cpu_transaction(void)
{
    u32 i;
    REG32(MODE)=1u; REG16(START)=0u;
    REG16(0x380042u)=29u; REG16(0x38004cu)=159u;
    for(i=0;i<4800u;++i)((volatile u32 *)FB)[i]=i*0x01030507u;
    for(i=0;i<16u;++i)REG32(LUT+i*4u)=i*0x000c0c0cu;
    run_probe();
    return status==1u && restored && frames[0]==2u && frames[1]==2u;
}
#endif

static void log_value(FS_FILE *f,const char *name,u32 v)
{
    char line[80],digits[12];u32 len=0,n=0;
    while(name[len]) {line[len]=name[len];++len;}
    line[len++]='=';
    do {digits[n++]=(char)('0'+v%10u);v/=10u;}while(v);
    while(n)line[len++]=digits[--n];line[len++]='\n';
    fs_fwrite(line,1,len,f);
}

static T_WORD probe_window_proc(T_GUI_HWND w,T_WORD message,T_GUI_WPARAM wp,T_GUI_LPARAM lp)
{
    if(message==MSG_PAINT) {
        T_GUI_HDC dc=fnGUI_BeginPaint(w);
        fnGUI_TextOut(dc,4,12,(const T_BYTE *)(ui_phase<2u?
            "4 GRAY THEN 16 GRAY":"LCD TEST COMPLETE"));
        fnGUI_TextOut(dc,4,36,(const T_BYTE *)(ui_phase<2u?
            "AUTO START / AUTO RETURN":"SEE A:\\GRAY16.LOG"));
        fnGUI_EndPaint(w,dc);
        return 0;
    }
    if(message==MSG_TIMER && wp==1u) {
        ++ui_ticks;
        if(ui_phase==0u && ui_ticks>=40u)ui_phase=1u;
        if(ui_phase==2u && ui_ticks>=80u)fnGUI_PostMessage(w,MSG_CLOSE,0,0);
        return 0;
    }
    if(message==MSG_KEYUP && (wp==SCANCODE_ESCAPE || wp==SCANCODE_ENTER)) {
        if(ui_phase==2u || wp==SCANCODE_ESCAPE)fnGUI_PostMessage(w,MSG_CLOSE,0,0);
    }
    if(message==MSG_CLOSE) {
        if(!ui_closed) {
            ui_closed=1u;
            fnGUI_KillTimer(w,1);
            fnGUI_DestroyMainWindow(w);
            fnGUI_PostQuitMessage(w);
        }
        return 0;
    }
    return fnGUI_DefaultMainWinProc(w,message,wp,lp);
}

static void perform_session(void)
{
    FS_FILE *f;
    static const char header[]="[9288T GRAY16 PROBE 3]\nclock_hz=256\n";
    task_suspend_result=tpDL_ROS33Table->ros33_sus_tsk(3);
    task_resume_result=-1;
    run_probe();
    if(task_suspend_result==0)task_resume_result=tpDL_ROS33Table->ros33_rsm_tsk(3);
    f=fs_fopen("a:\\GRAY16.LOG","wb");
    if(f) {
        fs_fwrite(header,1,sizeof(header)-1u,f);
        log_value(f,"status",status);log_value(f,"restored",restored);
        log_value(f,"task_suspend_result",(u32)task_suspend_result);
        log_value(f,"task_resume_result",(u32)task_resume_result);
        log_value(f,"psr_before",psr_before);log_value(f,"psr_after",psr_after);
        log_value(f,"dp_before",dp_before);log_value(f,"dp_after",dp_after);
        log_value(f,"saved_mode",saved_mode);log_value(f,"saved_start",saved_start);
        log_value(f,"gray4_frames",frames[0]);log_value(f,"gray4_ticks",ticks[0]);
        log_value(f,"gray4_timed",finished[0]);
        log_value(f,"gray16_frames",frames[1]);log_value(f,"gray16_ticks",ticks[1]);
        log_value(f,"gray16_timed",finished[1]);
        fs_fwrite("[END]\n",1,6,f);fs_fclose(f);
    }
}

T_WORD App_Main(void)
{
    T_GUI_MainWinCreate info;
    T_GUI_Msg message;
    u32 i;
    for(i=0;i<2400u;++i)desktop[i]=((volatile u32 *)FB)[i];
    for(i=0;i<sizeof(info);++i)((u8 *)&info)[i]=0;
    info.dwStyle=WS_VISIBLE|WS_CAPTION;
    info.spCaption=(const T_BYTE *)"GRAY16 PROBE 3";
    info.MainWindowProc=probe_window_proc;
    info.rx=240;info.by=160;info.iBkColor=COLOR_LIGHTWHITE;info.hHosting=HWND_DESKTOP;
    ui_window=fnGUI_CreateMainWindow(&info);
    if(!ui_window || ui_window==HWND_INVALID)return -1;
    fnGUI_ShowWindow(ui_window,SW_SHOWNORMAL);
    fnGUI_SetActiveWindow(ui_window);fnGUI_SetFocus(ui_window);
    fnGUI_SetTimer(ui_window,1,1);
    while(fnGUI_GetMessage(&message,ui_window)) {
        fnGUI_TranslateMessage(&message);fnGUI_DispatchMessage(&message);
        if(ui_closed)continue;
        if(ui_phase==1u) {
            perform_session();
            ui_phase=2u;ui_ticks=0u;
            fnGUI_SetWindowCaption(ui_window,(const T_BYTE *)(status==1u?
                "LCD RESTORED / AUTO EXIT":"LCD PROBE SKIPPED/FAILED"));
            fnGUI_InvalidateRect(ui_window,0,1);
        }
    }
    if(!ui_closed)probe_window_proc(ui_window,MSG_CLOSE,0,0);
    fnGUI_ThrowAwayMessages(ui_window);fnGUI_MainWindowCleanup(ui_window);
    for(i=0;i<2400u;++i)((volatile u32 *)FB)[i]=desktop[i];
    return 0;
}

#ifdef GRAY16_TRANSACTION_TEST
/* Exercise the actual perform_session sequence with SDK mocks. The display is
 * real MMIO; only task/FS services are stubbed. GUI needs full firmware. */
T_GUI_RelocationTable *tpDL_GUITable;
T_ROS33_RelocationTable *tpDL_ROS33Table;
T_FS_RelocationTable *tpDL_FSTable;
static T_ROS33_RelocationTable mock_os;
static T_FS_RelocationTable mock_fs;
static u32 mock_suspended,mock_resumed,mock_errors,mock_opened;
static ER mock_suspend(ID id) { if(id!=3)++mock_errors;mock_suspended=1u;return 0; }
static ER mock_resume(ID id) { if(id!=3 || !mock_suspended)++mock_errors;mock_suspended=0u;++mock_resumed;return 0; }
static FS_FILE *mock_open(const char *path,const char *mode)
{
    (void)path;(void)mode;
    if((REG32(MODE)&7u)!=1u || mock_suspended)++mock_errors;
    ++mock_opened;
    return 0;
}
u32 cpu_app_lifecycle(void)
{
    u32 i;
    REG32(MODE)=1u;REG16(START)=0u;REG16(0x380042u)=29u;REG16(0x38004cu)=159u;
    for(i=0;i<4800u;++i)((volatile u32 *)FB)[i]=i*0x01030507u;
    tpDL_ROS33Table=&mock_os;tpDL_FSTable=&mock_fs;
    mock_os.ros33_sus_tsk=mock_suspend;
    mock_os.ros33_rsm_tsk=mock_resume;mock_fs.fopen=mock_open;
    perform_session();
    return !mock_errors && mock_opened==1u && mock_resumed==1u && !mock_suspended
        && status==1u && restored && task_suspend_result==0 && task_resume_result==0
        && !((psr_before^psr_after)&16u) && dp_before==dp_after;
}
#endif
