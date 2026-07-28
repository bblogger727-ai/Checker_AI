import sys

resolution_code = """
        # === GLOBAL COLLISION RESOLUTION FOR THIS PAGE ===
        page_ticks = []
        page_stamps = []
        page_fbs = []
        page_p3 = []
        
        for mkey, qdata in _manifest["questions"].items():
            for i, t in enumerate(qdata.get("ticks_crosses", [])):
                if t["page"] == page_num:
                    page_ticks.append((t, "tick" if t["action"] == "tick" else "cross"))
            if qdata.get("stamp") and qdata["stamp"]["page"] == page_num:
                page_stamps.append((qdata["stamp"], qdata["stamp"]))
            if qdata.get("feedback") and qdata["feedback"]["page"] == page_num:
                page_fbs.append((qdata["feedback"], qdata["feedback"]))
                
        for t in _manifest.get("phase3_crosses", []):
            if t["page"] == page_num:
                page_p3.append((t, "cross"))

        def get_rect(obj, otype):
            if otype in ("tick", "cross"):
                sz = obj["size"]
                return (obj["x"] - sz/2, obj["y"] - sz/2, obj["x"] + sz/2, obj["y"] + sz/2)
            elif otype == "stamp":
                _f = int(28 * obj["scale"])
                _half_h = _f * 2 + int(4 * obj["scale"]) * 2 + _f * 0.20 + 10
                _half_w = _f * 3
                return (obj["x"] - _half_w, obj["y"] - _half_h, obj["x"] + _half_w, obj["y"] + _half_h)
            elif otype == "feedback":
                import textwrap
                wrapped = []
                for ln in obj["text"].split('\\n'):
                    wrapped.extend(textwrap.wrap(ln, width=50))
                num_lines = len(wrapped)
                bg_w = int(max(len(ln) for ln in wrapped + [""]) * (obj["font_size"] * 0.60) + 20)
                bg_h = int(obj["font_size"] * 1.5 * num_lines + obj["font_size"] * 0.6)
                bg_y = obj["y"] - (num_lines - 1) * obj["font_size"] * 1.5 - obj["font_size"] * 0.3 - 8
                return (obj["x"] - 10, bg_y, obj["x"] - 10 + bg_w, bg_y + bg_h)

        def _rects_overlap(r1, r2):
            return not (r1[2] < r2[0] or r1[0] > r2[2] or r1[3] < r2[1] or r1[1] > r2[3])

        movables = [("stamp", s[0]) for s in page_stamps] + [("feedback", f[0]) for f in page_fbs]
        fixed = [("tick", t[0]) for t in page_ticks] + [("cross", t[0]) for t in page_p3]
        
        for _ in range(15):
            moved_any = False
            for m_type, m_obj in movables:
                m_rect = get_rect(m_obj, m_type)
                
                all_others = [("tick", t[0]) for t in page_ticks] + \
                             [("cross", t[0]) for t in page_p3] + \
                             [("stamp", s[0]) for s in page_stamps if s[0] is not m_obj] + \
                             [("feedback", f[0]) for f in page_fbs if f[0] is not m_obj]
                             
                for o_type, o_obj in all_others:
                    o_rect = get_rect(o_obj, o_type)
                    if _rects_overlap(m_rect, o_rect):
                        dx1 = o_rect[2] - m_rect[0] + 8
                        dx2 = o_rect[0] - m_rect[2] - 8
                        dy1 = o_rect[3] - m_rect[1] + 8
                        dy2 = o_rect[1] - m_rect[3] - 8
                        
                        moves = [
                            (dx1, 0, abs(dx1)),
                            (dx2, 0, abs(dx2)),
                            (0, dy1, abs(dy1)),
                            (0, dy2, abs(dy2)),
                        ]
                        moves.sort(key=lambda x: x[2])
                        best_move = moves[0]
                        m_obj["x"] += best_move[0]
                        m_obj["y"] += best_move[1]
                        
                        m_obj["x"] = max(50, min(pdf_w - 50, m_obj["x"]))
                        m_obj["y"] = max(50, min(pdf_h - 50, m_obj["y"]))
                        moved_any = True
                        break
            if not moved_any:
                break
                
        # === DRAW PHASE ===
        for t, act in page_ticks:
            if act == "tick":
                _draw_tick(c, t["x"], t["y"], size=t["size"])
            else:
                _draw_cross(c, t["x"], t["y"], size=t["size"])
                
        for t, act in page_p3:
            _draw_cross(c, t["x"], t["y"], size=t["size"])
            
        for s, _ in page_stamps:
            _draw_marks_stamp(
                c, 
                x=s["x"], 
                y=s["y"], 
                marks_obtained=s["marks_obtained"],
                marks_total=s["marks_total"],
                page_scale=s["scale"]
            )
            
        for f, _ in page_fbs:
            fb_text = f["text"]
            fb_x_final = f["x"]
            fb_y_final = f["y"]
            FB_FONT_SIZE = f["font_size"]
            
            import textwrap
            wrapped_lines = []
            for line in fb_text.split('\\n'):
                wrapped_lines.extend(textwrap.wrap(line, width=50))
            fb_num_lines = len(wrapped_lines)
            
            c.saveState()
            bg_w = int(max(len(ln) for ln in wrapped_lines + [""]) * (FB_FONT_SIZE * 0.60) + 20)
            bg_h = int(FB_FONT_SIZE * 1.5 * fb_num_lines + FB_FONT_SIZE * 0.6)
            bg_y = fb_y_final - (fb_num_lines - 1) * FB_FONT_SIZE * 1.5 - FB_FONT_SIZE * 0.3 - 8
            
            c.setFillColorRGB(1, 1, 1)
            c.setStrokeColorRGB(1, 1, 1, 0)
            c.rect(fb_x_final - 10, bg_y, bg_w, bg_h, fill=1, stroke=0)
            
            c.setFont("Helvetica-Bold", FB_FONT_SIZE)
            c.setFillColorRGB(1, 0, 0)
            c.setStrokeColorRGB(1, 0, 0)
            
            _draw_y = fb_y_final
            for line in wrapped_lines:
                c.drawString(fb_x_final, _draw_y, line)
                _draw_y -= FB_FONT_SIZE * 1.5
            c.restoreState()
"""

with open('generate_checked_copy_v2.py', 'r') as f:
    lines = f.readlines()

for i in range(len(lines)):
    if 'c.showPage()' in lines[i] and 'def' not in lines[i]:
        # We need to find the correct indentation level. It's usually 8 spaces.
        if lines[i].startswith('        c.showPage()'):
            lines.insert(i, resolution_code + '\n')
            break

with open('generate_checked_copy_v2.py', 'w') as f:
    f.writelines(lines)
