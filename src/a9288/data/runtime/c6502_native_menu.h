#ifdef C6502_NEEDS_c6502_adapter_guimenu
/* C6502 dictsys.h packed layouts (guest 16-bit pointers):
   Menu: {itemNum,colNum,colPos:u16,style,menuItems:u16}
   Item: {strLen,str:u16,bmpData0:u16,bmpData1:u16}
   Env:  {x0,x1,y0,y1,startDispItem,maxDispItem,dispItemNum,nFocus}.
   Never cast these bytes to a host struct or pass them to 9288 GuiMenu. */
static c6502_u16 menu_item(c6502_u16 menu, c6502_u32 index)
{
    return guest_get16((c6502_u16)(guest_get16(menu + 5u) + index * 2u));
}

static void menu_highlight(c6502_u16 menu, c6502_u16 env,
    c6502_u32 focus, int selected)
{
    c6502_u32 columns = guest_read(menu + 1u), row, y, x, width;
    c6502_u16 item = menu_item(menu, guest_read(env + 4u) + focus);
    if (!columns) return;
    row = focus / columns;
    x = guest_read(env) + guest_read((c6502_u16)(
        guest_get16(menu + 2u) + focus % columns));
    y = guest_read(env + 2u) + row * 16u;
    width = guest_read(item) * 8u;
    if (guest_read(menu + 4u) & 1u) {
        native_picture((c6502_u8)x, (c6502_u8)y,
            (c6502_u8)(x + 15u), (c6502_u8)(y + 15u),
            guest_get16(item + (selected ? 5u : 3u)), 0u);
        x += 16u;
    }
    if (width && x < 159u && y < 96u) {
        c6502_u32 right = x + width - 2u, bottom = y + 15u;
        if (right > 158u) right = 158u;
        if (bottom > 95u) bottom = 95u;
        for (; y <= bottom; ++y)
            horizontal_span((c6502_u8)x, (c6502_u8)right, (c6502_u8)y, 2);
    }
}

static void menu_scroll(c6502_u16 menu, c6502_u16 env, c6502_u32 focus)
{
    c6502_u32 selected = guest_read(env + 4u) + focus;
    c6502_u32 count = guest_read(menu);
    native_icon_left_scroll((c6502_u8)((selected + 1u) * 100u / count));
    native_icon_arrow(1, selected != 0u);
    native_icon_arrow(0, selected + 1u < count);
}

static void menu_draw(c6502_u16 menu, c6502_u16 env, c6502_u32 focus)
{
    c6502_u32 i, y, columns = guest_read(menu + 1u);
    c6502_u32 start = guest_read(env + 4u), count = guest_read(menu) - start;
    if (count > guest_read(env + 5u)) count = guest_read(env + 5u);
    guest_write(env + 6u, (c6502_u8)count);
    NATIVE_LINEAR_BEGIN();
    for (y = guest_read(env + 2u); y <= guest_read(env + 3u); ++y)
        horizontal_span(guest_read(env), guest_read(env + 1u), (c6502_u8)y, 0);
    for (i = 0u; i < count; ++i) {
        c6502_u32 x = guest_read(env) + guest_read((c6502_u16)(
            guest_get16(menu + 2u) + i % columns));
        c6502_u16 item = menu_item(menu, start + i), text = guest_get16(item + 1u);
        c6502_u32 length = 0u;
        y = guest_read(env + 2u) + i / columns * 16u;
        if (guest_read(menu + 4u) & 1u) {
            if (i != focus) native_picture((c6502_u8)x, (c6502_u8)y,
                (c6502_u8)(x + 15u), (c6502_u8)(y + 15u),
                guest_get16(item + 3u), 0u);
            x += 16u;
        }
        while (length + 1u < C6502_RESOURCE_SCRATCH_SIZE) {
            c6502_resource_scratch[length] = guest_read((c6502_u16)(text + length));
            if (!c6502_resource_scratch[length++]) break;
        }
        c6502_resource_scratch[length] = 0u;
        native_text((c6502_u8)x, (c6502_u8)y, c6502_resource_scratch);
    }
    menu_highlight(menu, env, focus, 1);
    menu_scroll(menu, env, focus);
    NATIVE_LINEAR_END();
}

static void menu_run(c6502_u32 *r, c6502_u16 menu, c6502_u16 env)
{
    c6502_u32 count = guest_read(menu), columns = guest_read(menu + 1u);
    c6502_u32 maximum, start, selected = (c6502_u8)r[4], focus, i;
    c6502_u16 old_keyboard = c6502_native_state.keyboard_state;
    c6502_u8 old_filter = c6502_native_state.input_filter;
    c6502_u8 old_type = c6502_native_state.keyboard_type, icons[96], result;
    c6502_u32 y0 = guest_read(env + 2u), y1 = guest_read(env + 3u);
    if (!count || !columns || y1 < y0 || y1 >= 96u ||
        guest_read(env) > guest_read(env + 1u) || guest_read(env + 1u) >= 160u) {
        return8(r, 0xffu); return;
    }
    maximum = ((y1 - y0 + 1u) / 16u) * columns;
    if (!maximum) { return8(r, 0xffu); return; }
    if (maximum > count) maximum = count;
    guest_write(env + 5u, (c6502_u8)maximum);
    start = guest_read(env + 4u);
    if (start > count) start = 0u;
    if (selected >= count) selected = count - 1u;
    if (selected < start || selected >= start + maximum) start = 0u;
    if (selected >= start + maximum)
        start = (selected / columns + 1u) * columns - maximum;
    if (start > selected) start = selected;
    guest_write(env + 4u, (c6502_u8)start);
    focus = selected - start;
    for (i = 0u; i < 96u; ++i)
        icons[i] = guest_read((c6502_u16)(0x412u + i * 32u)) & 1u;
    c6502_native_state.input_filter = 3u;
    c6502_native_state.keyboard_type = 2u;
    menu_draw(menu, env, focus);
    c6502_native_present();
    for (;;) {
        c6502_u32 previous = selected, previous_start = start;
        c6502_u8 type, key = translate_key(native_window_key(1), &type);
        native_update_timer();
        c6502_timer_pending = 0u;
        c6502_native_state.ram[0x201eu] &= 0xfeu;
        if (type == 2u) {
            /* The ROM accepts 1..9 and returns the visible item immediately. */
            if (key >= '1' && key <= '9' &&
                key - '1' < guest_read(env + 6u)) {
                result = (c6502_u8)(start + key - '1'); break;
            }
            continue;
        }
        if (type != 5u) continue;
        if (key == 0x27u) { result = (c6502_u8)selected; break; }
        if (key == 0x28u) {
            guest_write(env + 7u, (c6502_u8)selected);
            result = 0xffu; break;
        }
        if (key == 0x24u || key == 0x22u) {
            c6502_u32 step = key == 0x22u ? columns : 1u;
            if (selected >= step) selected -= step;
            else if (selected && (guest_read(menu + 4u) & 2u)) selected = 0u;
            else if (!selected && (guest_read(menu + 4u) & 2u)) selected = count - 1u;
        } else if (key == 0x25u || key == 0x23u) {
            c6502_u32 step = key == 0x23u ? columns : 1u;
            if (selected + step < count) selected += step;
            else if (selected + 1u < count &&
                ((guest_read(menu + 4u) & 2u) ||
                 selected / columns < (count - 1u) / columns)) selected = count - 1u;
            else if (selected + 1u == count && (guest_read(menu + 4u) & 2u)) selected = 0u;
        } else if (key == 0x20u) {
            if (start >= maximum) { start -= maximum; selected = start; }
            else if (start) {
                start = 0u;
                if (selected >= maximum) selected = 0u;
            }
        } else if (key == 0x21u) {
            if (start + maximum < count) { start += maximum; selected = start; }
        }
        if (selected < start) start = selected / columns * columns;
        else if (selected >= start + maximum)
            start = (selected / columns + 1u) * columns - maximum;
        focus = selected - start;
        if (previous_start != start) {
            guest_write(env + 4u, (c6502_u8)start);
            menu_draw(menu, env, focus);
        } else if (selected != previous) {
            NATIVE_LINEAR_BEGIN();
            menu_highlight(menu, env, previous - start, 0);
            menu_highlight(menu, env, focus, 1);
            menu_scroll(menu, env, focus);
            NATIVE_LINEAR_END();
        }
        if (selected != previous || start != previous_start) c6502_native_present();
        native_refresh_if_due();
    }
    for (i = 0u; i < 96u; ++i) {
        c6502_u16 address = (c6502_u16)(0x412u + i * 32u);
        guest_write(address, (c6502_u8)((guest_read(address) & 0xfeu) | icons[i]));
    }
    c6502_native_state.keyboard_state = old_keyboard;
    c6502_native_state.input_filter = old_filter;
    c6502_native_state.keyboard_type = old_type;
    return8(r, result);
}
#endif
