import re

with open("generate_checked_copy_v2.py", "r") as f:
    content = f.read()

replacement = """
            # ── Final overlap check against ALL drawn items on this page ──
            # First, if feedback was placed for THIS question, add it to rects
            # so we avoid it just like previous questions' rects.
            if placed and fb_y_final is not None:
                FB_FSZ = int(11 * page_scale)
                page_drawn_rects_y.append((fb_y_final, fb_y_final + FB_FSZ))

            # Nudge stamp if it overlaps with any feedback or stamp from this or earlier questions
            if _pending_stamp is not None and final_stamp_y is not None:
                half_h_f = _pending_stamp["half_h_pts"]
                
                s_bot_f  = final_stamp_y - half_h_f
                s_top_f  = final_stamp_y + half_h_f

                for r_bot, r_top in page_drawn_rects_y:
                    if min(s_top_f, r_top) - max(s_bot_f, r_bot) > 0:
                        below_y_f = r_bot - half_h_f - 8
                        above_y_f = r_top + half_h_f + 8
                        if below_y_f >= half_h_f + 4:
                            final_stamp_y = below_y_f
                        else:
                            final_stamp_y = min(above_y_f, pdf_h * 0.88 - half_h_f)
                        # Update our own bounds for the next rect check
                        s_bot_f  = final_stamp_y - half_h_f
                        s_top_f  = final_stamp_y + half_h_f
                        print(f"    ↑ Stamp adjusted to y={final_stamp_y:.0f} to clear rect {r_bot:.0f}-{r_top:.0f}", flush=True)

                # ── Right-margin fallback ──────────────────────────────────
                still_collides = any(
                    min(s_top_f, r_top) - max(s_bot_f, r_bot) > 0
                    for r_bot, r_top in page_drawn_rects_y
                )
                if still_collides:
                    _pending_stamp["x"] = pdf_w * 0.88
                    print(f"    → Stamp moved to right margin (x={pdf_w * 0.88:.0f}) to avoid collision", flush=True)

                # Draw stamp exactly once at its final collision-free position
                stamp_half_h = _pending_stamp["half_h_pts"]
                _draw_marks_stamp(
                    c,
                    _pending_stamp["x"],
                    final_stamp_y,
                    _pending_stamp["marks_obtained"],
                    _pending_stamp["marks_total"],
                    font_name,
                    scale=page_scale,
                )
                # v2: record stamp
                _manifest["questions"][_mkey]["stamp"] = {
                    "page":  page_num,
                    "x":     _pending_stamp["x"],
                    "y":     final_stamp_y,
                    "scale": page_scale,
                }
                _pending_stamp = None   # consumed — prevent double draw below
                page_drawn_rects_y.append((final_stamp_y - stamp_half_h, final_stamp_y + stamp_half_h))

            # Draw feedback
            if placed and fb_text:
                c.saveState()
                
                # Draw a white background box to hide noise/scan lines
                bg_padding_x = 4
                bg_padding_y = 4
                bg_h = fb_num_lines * FB_FONT_SIZE * 1.5 + bg_padding_y * 2
                bg_w = fb_text_w_pt + bg_padding_x * 2
                bg_y = fb_y_final - (fb_num_lines - 1) * FB_FONT_SIZE * 1.5 - FB_FONT_SIZE * 0.3 - bg_padding_y
                
                c.setFillColorRGB(1, 1, 1)
                c.setStrokeColorRGB(1, 1, 1, 0)
                c.rect(fb_x_final - bg_padding_x, bg_y, bg_w, bg_h, fill=1, stroke=0)
                
                c.setFont(font_name, FB_FONT_SIZE)
                c.setFillColor(red)
                c.setStrokeColor(red)
                c.setLineWidth(1.8)
                
                # Wrap text here to prevent it from stretching across the page and overlapping right-margin stamps
                import textwrap
                wrapped_lines = []
                for line in fb_text.split('\n'):
                    wrapped_lines.extend(textwrap.wrap(line, width=50))
                
                _draw_y = fb_y_final
                for line in wrapped_lines:
                    c.drawString(fb_x_final, _draw_y, line)
                    _draw_y -= FB_FONT_SIZE * 1.5
                    
                c.setLineWidth(0)
                
                _draw_y = fb_y_final
                for line in wrapped_lines:
                    c.drawString(fb_x_final, _draw_y, line)
                    _draw_y -= FB_FONT_SIZE * 1.5

                c.restoreState()

                # v2: record feedback
                _manifest["questions"][_mkey]["feedback"] = {
                    "text":      fb_text,
                    "page":      page_num,
                    "x":         fb_x_final,
                    "y":         fb_y_final,
                    "font_size": FB_FONT_SIZE,
                    "scale":     page_scale,
                }
"""

start_idx = content.find("            if placed:\n")
end_idx = content.find("                    }\n", start_idx)
if end_idx != -1:
    end_idx += 22

if start_idx == -1 or end_idx == -1:
    print("Could not find block")
    exit(1)

new_content = content[:start_idx] + replacement.strip('\n') + "\n" + content[end_idx:]

with open("generate_checked_copy_v2.py", "w") as f:
    f.write(new_content)

print("Patched successfully")
