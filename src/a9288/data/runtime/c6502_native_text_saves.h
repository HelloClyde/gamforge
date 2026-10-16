/* Bounded auxiliary metadata for SysSaveScreen. Raw saved guest bytes keep
 * their original format. A changed/reused buffer safely drops the overlay. */
typedef struct NativeTextSave {
    NativeTextSnapshot *layer;
    c6502_u8 *bytes;
    c6502_u16 buffer,length,banks[16];
} NativeTextSave;
static NativeTextSave native_text_saves[4];
static c6502_u32 native_text_save_cursor,native_text_save_count;

/* Metadata may reread a save buffer, so admit only ordinary RAM whose
 * accesses have no guest side effects. In particular, DATA ports increment
 * pointers and an LCD alias can modify the picture while SaveScreen copies
 * it. The original ordered guest copy still handles every rejected buffer;
 * only the optional target-resolution provenance is omitted. */
static int native_text_save_buffer_safe(c6502_u16 buffer,c6502_u32 length)
{
    c6502_u32 cursor=buffer,end=cursor+length;
    if(!length || end>0x10000u) return 0;
    while(cursor<end) {
        c6502_u32 next=(cursor|0xfffu)+1u,physical,size;
        if(next>end) next=end;
        size=next-cursor;
        physical=cursor<0x4000u ? cursor :
            ((c6502_u32)c6502_native_state.banks[cursor>>12]<<12)|(cursor&0xfffu);
        if(physical>=C6502_RAM_SIZE || size>C6502_RAM_SIZE-physical) return 0;
        if(physical<0x1001u && physical+size>0x400u) return 0;
        if(cursor<0x4000u) {
            if(cursor<4u ||
                (cursor<0x0fu && next>0x0cu) ||
                (cursor<=0x21bu && next>0x21bu) ||
                (cursor<0x400u && next>0x300u) ||
                (cursor<=0x2028u && next>0x2028u)) return 0;
        }
        cursor=next;
    }
    return 1;
}

static void native_text_save_forget(NativeTextSave *s)
{
    if(s->layer) {native_text_layer_free(s->layer);--native_text_save_count;}
    if(s->bytes) free(s->bytes);
    s->layer=0;s->bytes=0;
}
static void native_text_saves_reset(void)
{
    c6502_u32 i;
    for(i=0u;i<4u;++i) native_text_save_forget(native_text_saves+i);
    native_text_save_cursor=native_text_save_count=0u;
}
static void native_text_save_record(c6502_u16 buffer,c6502_u32 first,
    c6502_u32 last,c6502_u32 top,c6502_u32 bottom)
{
    c6502_u32 i,length,slot=4u;
    NativeTextSave *s;
    for(i=0u;i<4u;++i) if(native_text_saves[i].layer && native_text_saves[i].buffer==buffer) {slot=i;break;}
    /* Reusing a save buffer invalidates its old text even when the new
     * screen contains no text. Do not evict unrelated records in that case. */
    if(slot<4u) native_text_save_forget(native_text_saves+slot);
    if(!native_text_active_rows || first>last || last>=20u || top>bottom || bottom>=96u) return;
    length=(last-first+1u)*(bottom-top+1u);
    if(!native_text_save_buffer_safe(buffer,length)) return;
    if(slot==4u) {slot=native_text_save_cursor++ & 3u;native_text_save_forget(native_text_saves+slot);}
    s=native_text_saves+slot;
    s->layer=native_text_layer_save(first,last,top,bottom);
    if(!s->layer)return;
    s->buffer=buffer;s->length=(c6502_u16)length;
    s->bytes=(c6502_u8 *)malloc(s->length);
    if(!s->bytes){native_text_layer_free(s->layer);s->layer=0;return;}
    for(i=0u;i<16u;++i)s->banks[i]=c6502_native_state.banks[i];
    for(i=0u;i<s->length;++i)s->bytes[i]=guest_read((c6502_u16)(buffer+i));
    ++native_text_save_count;
}
static const NativeTextSnapshot *native_text_saved(c6502_u16 buffer,
    c6502_u32 first,c6502_u32 last,c6502_u32 top,c6502_u32 bottom)
{
    c6502_u32 n,i;
    if(!native_text_save_count) return 0;
    if(first>last || last>=20u || top>bottom || bottom>=96u) return 0;
    for(n=0u;n<4u;++n) {
        const NativeTextSave *s=native_text_saves+n;
        if(!s->layer || s->buffer!=buffer || s->layer->first!=first ||
            s->layer->last!=last || s->layer->top!=top || s->layer->bottom!=bottom)continue;
        for(i=0u;i<16u;++i)if(s->banks[i]!=c6502_native_state.banks[i])break;
        if(i!=16u)continue;
        if(!native_text_save_buffer_safe(buffer,s->length))continue;
        for(i=0u;i<s->length;++i)if(s->bytes[i]!=guest_read((c6502_u16)(buffer+i)))break;
        if(i==s->length)return s->layer;
    }
    return 0;
}
