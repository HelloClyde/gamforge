#ifndef C6502_NATIVE_RESOURCES_H
#define C6502_NATIVE_RESOURCES_H
/* Immutable disk pages + bounded session-only copy-on-write pages.
   No code execution, whole-image allocation or writes to the RES file. */
#define NR_PAGE 4096u
#define NR_SLOTS 32u
#define NR_DIRTY_LIMIT 64u
static FS_FILE *nr_file;
static c6502_u8 *nr_cache, *nr_crcs;
static c6502_u8 **nr_dirty;
static c6502_u32 nr_tags[NR_SLOTS], nr_pages, nr_offset;
static c6502_u32 nr_hits, nr_misses, nr_writes, nr_dirty_count, nr_error;
c6502_u32 c6502_resource_entry_sp;
extern void c6502_native_resource_abort(void) __attribute__((noreturn));

static c6502_u32 nr_u32(const c6502_u8 *p)
{
    return p[0] | ((c6502_u32)p[1]<<8) | ((c6502_u32)p[2]<<16) | ((c6502_u32)p[3]<<24);
}
static c6502_u32 nr_crc(const c6502_u8 *p, c6502_u32 n)
{
    static const c6502_u32 table[16] = {
        0,0x1db71064u,0x3b6e20c8u,0x26d930acu,0x76dc4190u,0x6b6b51f4u,0x4db26158u,0x5005713cu,
        0xedb88320u,0xf00f9344u,0xd6d6a3e8u,0xcb61b38cu,0x9b64c2b0u,0x86d3d2d4u,0xa00ae278u,0xbdbdf21cu
    };
    c6502_u32 crc=0xffffffffu;
    while (n--) {
        crc ^= *p++;
        crc = (crc>>4)^table[crc&15u]; crc = (crc>>4)^table[crc&15u];
    }
    return crc^0xffffffffu;
}
static void nr_fail(c6502_u32 error)
{
    if (!nr_error) nr_error=error;
    if (c6502_resource_entry_sp) c6502_native_resource_abort();
}
static void nr_close(void)
{
    c6502_u32 i;
    c6502_resource_entry_sp=0;
    if (nr_file) { (void)fs_fclose(nr_file); nr_file=0; }
    if (nr_dirty) {
        for (i=0;i<nr_pages;++i) if (nr_dirty[i]) free(nr_dirty[i]);
        free(nr_dirty); nr_dirty=0;
    }
    if (nr_cache) { free(nr_cache); nr_cache=0; }
    if (nr_crcs) { free(nr_crcs); nr_crcs=0; }
}
static int nr_open(void)
{
    static const c6502_u8 expected[64]=C6502_RESOURCE_HEADER;
    c6502_u8 header[64];
    c6502_u32 i;
    nr_close(); nr_error=nr_hits=nr_misses=nr_writes=nr_dirty_count=0;
    nr_pages=(C6502_GAME_SIZE+NR_PAGE-1u)/NR_PAGE;
    nr_offset=64u+nr_pages*4u;
    nr_file=fs_fopen(C6502_RESOURCE_PATH,"rb");
    if (!nr_file) { nr_fail(1); return 0; }
    if (fs_fread(header,1,64,nr_file)!=64u) { nr_fail(2); return 0; }
    for (i=0;i<64u;++i) if (header[i]!=expected[i]) { nr_fail(2); return 0; }
    if (fs_fseek(nr_file,0,SEEK_END)<0 ||
        fs_ftell(nr_file)!=(long)(nr_offset+C6502_GAME_SIZE) ||
        fs_fseek(nr_file,64,SEEK_SET)<0) { nr_fail(2); return 0; }
    nr_crcs=(c6502_u8 *)malloc(nr_pages*4u);
    nr_cache=(c6502_u8 *)malloc(NR_SLOTS*NR_PAGE);
    nr_dirty=(c6502_u8 **)malloc(nr_pages*sizeof(*nr_dirty));
    if (nr_dirty) bytes_set((c6502_u8 *)nr_dirty,0,nr_pages*sizeof(*nr_dirty));
    if (!nr_crcs || !nr_cache || !nr_dirty) { nr_fail(3); return 0; }
    if (fs_fread(nr_crcs,1,nr_pages*4u,nr_file)!=nr_pages*4u ||
        nr_crc(nr_crcs,nr_pages*4u)!=nr_u32(header+60)) { nr_fail(2); return 0; }
    for (i=0;i<NR_SLOTS;++i) nr_tags[i]=0xffffffffu;
    return 1;
}
static c6502_u8 *nr_page(c6502_u32 offset)
{
    c6502_u32 page=offset/NR_PAGE, slot=page&(NR_SLOTS-1u), size;
    c6502_u8 *p;
    if (nr_error || offset>=C6502_GAME_SIZE) { nr_fail(4); return 0; }
    if (nr_dirty[page]) { ++nr_hits; return nr_dirty[page]; }
    p=nr_cache+slot*NR_PAGE;
    if (nr_tags[slot]==page) { ++nr_hits; return p; }
    ++nr_misses; nr_tags[slot]=0xffffffffu;
    size=C6502_GAME_SIZE-page*NR_PAGE;
    if (size>NR_PAGE) size=NR_PAGE;
    if (fs_fseek(nr_file,(long)(nr_offset+page*NR_PAGE),SEEK_SET)<0 ||
        fs_fread(p,1,size,nr_file)!=size) { nr_fail(4); return 0; }
    if (nr_crc(p,size)!=nr_u32(nr_crcs+page*4u)) { nr_fail(5); return 0; }
    bytes_set(p+size,0,NR_PAGE-size);
    nr_tags[slot]=page;
    return p;
}
static c6502_u8 nr_read(c6502_u32 offset)
{
    c6502_u8 *p=nr_page(offset);
    return p ? p[offset&(NR_PAGE-1u)] : 0;
}
static void nr_write(c6502_u32 offset, c6502_u8 value)
{
    c6502_u8 *p=nr_page(offset);
    c6502_u32 page=offset/NR_PAGE;
    if (!p || p[offset&(NR_PAGE-1u)]==value) return;
    if (!nr_dirty[page]) {
        if (nr_dirty_count>=NR_DIRTY_LIMIT) { nr_fail(6); return; }
        nr_dirty[page]=(c6502_u8 *)malloc(NR_PAGE);
        if (!nr_dirty[page]) { nr_fail(3); return; }
        bytes_copy(nr_dirty[page],p,NR_PAGE); ++nr_dirty_count;
    }
    nr_dirty[page][offset&(NR_PAGE-1u)]=value; ++nr_writes;
}
/* The drawing caller may hold this pointer only until its next resource
   access. Current whole-picture fast paths only write ordinary LCD RAM. */
static const c6502_u8 *nr_span(c6502_u32 offset,c6502_u32 size)
{
    c6502_u8 *p;
    if (!size || offset>=C6502_GAME_SIZE || size>C6502_GAME_SIZE-offset ||
        size>NR_PAGE-(offset&(NR_PAGE-1u))) return 0;
    p=nr_page(offset);
    return p ? p+(offset&(NR_PAGE-1u)) : 0;
}
#endif
