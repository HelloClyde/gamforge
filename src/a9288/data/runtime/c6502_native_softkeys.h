/* 9288S: 160x120 upper game area, 160x120 lower touch keyboard.
 * No SDK text rasterisation, framebuffer mode switch or IRAM takeover.
 * Glyphs are an explicit 5x7 UI font, not game-specific artwork. */
#ifndef C6502_NATIVE_SOFTKEYS_H
#define C6502_NATIVE_SOFTKEYS_H
#define C6502_S_KEYBOARD_Y 120u
#define C6502_S_KEY_COUNT 45u
typedef struct C6502_S_Key {
    c6502_u8 x, y, width, row, mask;
    const char *label;
} C6502_S_Key;
#define SKEY(x,y,w,r,c,label) {x,y,w,r,1u<<(c),label}
static const C6502_S_Key c6502_s_keys[C6502_S_KEY_COUNT] = {
    SKEY(0,120,16,1,0,"1"), SKEY(16,120,16,2,0,"2"),
    SKEY(32,120,16,3,0,"3"), SKEY(48,120,16,4,0,"4"),
    SKEY(64,120,16,5,0,"5"), SKEY(80,120,16,6,0,"6"),
    SKEY(96,120,16,7,0,"7"), SKEY(112,120,16,3,4,"8"),
    SKEY(128,120,16,4,4,"9"), SKEY(144,120,16,0,0,"0"),
    SKEY(0,140,16,0,1,"Q"), SKEY(16,140,16,1,1,"W"),
    SKEY(32,140,16,2,1,"E"), SKEY(48,140,16,3,1,"R"),
    SKEY(64,140,16,4,1,"T"), SKEY(80,140,16,5,1,"Y"),
    SKEY(96,140,16,6,1,"U"), SKEY(112,140,16,7,1,"I"),
    SKEY(128,140,16,0,4,"O"), SKEY(144,140,16,1,4,"P"),
    SKEY(0,160,16,0,2,"A"), SKEY(16,160,16,1,2,"S"),
    SKEY(32,160,16,2,2,"D"), SKEY(48,160,16,3,2,"F"),
    SKEY(64,160,16,4,2,"G"), SKEY(80,160,16,5,2,"H"),
    SKEY(96,160,16,6,2,"J"), SKEY(112,160,16,7,2,"K"),
    SKEY(128,160,16,2,4,"L"), SKEY(144,160,16,2,6,"PU"),
    SKEY(0,180,16,0,3,"Z"), SKEY(16,180,16,1,3,"X"),
    SKEY(32,180,16,2,3,"C"), SKEY(48,180,16,3,3,"V"),
    SKEY(64,180,16,4,3,"B"), SKEY(80,180,16,5,3,"N"),
    SKEY(96,180,16,6,3,"M"), SKEY(112,180,32,6,5,"SPACE"),
    SKEY(144,180,16,3,6,"PD"),
    SKEY(0,200,40,7,5,"LEFT"), SKEY(40,200,40,7,3,"UP"),
    SKEY(80,200,40,7,4,"DOWN"), SKEY(120,200,40,7,6,"RIGHT"),
    SKEY(0,220,80,1,6,"ENTER"), SKEY(80,220,80,0,6,"ESC")
};
#undef SKEY
/* 0..9, A..Z, then space. One column's seven bits, top bit first. */
static const c6502_u8 c6502_s_font[][5] = {
    {62,81,73,69,62},{0,66,127,64,0},{66,97,81,73,70},{33,65,69,75,49},
    {24,20,18,127,16},{39,69,69,69,57},{60,74,73,73,48},{1,113,9,5,3},
    {54,73,73,73,54},{6,73,73,41,30},
    {126,17,17,17,126},{127,73,73,73,54},{62,65,65,65,34},
    {127,65,65,34,28},{127,73,73,73,65},{127,9,9,9,1},
    {62,65,73,73,122},{127,8,8,8,127},{0,65,127,65,0},
    {32,64,65,63,1},{127,8,20,34,65},{127,64,64,64,64},
    {127,2,12,2,127},{127,4,8,16,127},{62,65,65,65,62},
    {127,9,9,9,6},{62,65,81,33,94},{127,9,25,41,70},
    {70,73,73,73,49},{1,1,127,1,1},{63,64,64,64,63},
    {31,32,64,32,31},{63,64,56,64,63},{99,20,8,20,99},
    {7,8,112,8,7},{97,81,73,69,67},{0,0,0,0,0}
};
static c6502_u8 c6502_s_touch_key = 0xffu;
static c6502_u8 c6502_s_touch_down;
static c6502_u32 c6502_s_touch_events, c6502_s_touch_presses;

static c6502_u8 native_s_hit_key(int x, int y)
{
    c6502_u32 i;
    if (x < 0 || x >= 160 || y < 120 || y >= 240) return 0xffu;
    for (i = 0u; i < C6502_S_KEY_COUNT; ++i) {
        const C6502_S_Key *key = c6502_s_keys + i;
        if (x >= key->x && x < key->x + key->width &&
            y >= key->y && y < key->y + 20) return (c6502_u8)i;
    }
    return 0xffu;
}

static void native_s_matrix(c6502_u8 current[8], c6502_u8 k5, c6502_u8 p0)
{
    c6502_u32 i;
    for (i = 0u; i < 8u; ++i) current[i] = 0u;
    if (!(k5 & 1u)) current[7] |= 64u;
    if (!(k5 & 2u)) current[7] |= 32u;
    if (!(k5 & 4u)) current[7] |= 16u;
    if (!(k5 & 8u)) current[7] |= 8u;
    if (!(p0 & 16u)) current[0] |= 64u;
    if (!(p0 & 32u)) current[1] |= 64u;
    if (c6502_s_touch_key < C6502_S_KEY_COUNT) {
        const C6502_S_Key *key = c6502_s_keys + c6502_s_touch_key;
        current[key->row] |= key->mask;
    }
}

static void native_s_ui_pixel(c6502_u8 *surface, c6502_u32 x, c6502_u32 y,
    c6502_u32 color)
{
    c6502_u32 offset = y * C6502_HOST_STRIDE + x / 4u;
    c6502_u32 shift = 6u - (x & 3u) * 2u;
    surface[offset] = (surface[offset] & ~(3u << shift)) | (color << shift);
}

static void native_s_keyboard_paint(c6502_u8 *surface)
{
    c6502_u32 i, x, y;
    for (i = 0u; i < C6502_S_KEY_COUNT; ++i) {
        const C6502_S_Key *key = c6502_s_keys + i;
        const char *text = key->label;
        c6502_u32 length = 0u, pressed = i == c6502_s_touch_key;
        for (y = key->y; y < key->y + 20u; ++y)
            for (x = key->x; x < key->x + key->width; ++x)
                native_s_ui_pixel(surface, x, y,
                    (x == key->x || y == key->y || x == key->x + key->width - 1u ||
                     y == key->y + 19u) ? 0u : pressed ? 1u : 3u);
        while (text[length]) ++length;
        x = key->x + (key->width - (length * 6u - 1u)) / 2u;
        while (*text) {
            c6502_u32 column, row;
            c6502_u8 ch = (c6502_u8)*text++;
            c6502_u32 glyph = ch >= '0' && ch <= '9' ? ch - '0' :
                ch >= 'A' && ch <= 'Z' ? ch - 'A' + 10u : 36u;
            for (column = 0u; column < 5u; ++column)
                for (row = 0u; row < 7u; ++row)
                    if (c6502_s_font[glyph][column] & (1u << row))
                        native_s_ui_pixel(surface, x + column, key->y + 6u + row,
                            pressed ? 3u : 0u);
            x += 6u;
        }
    }
}
#endif
