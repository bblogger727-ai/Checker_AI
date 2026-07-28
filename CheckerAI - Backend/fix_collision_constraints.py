import sys

filepath = 'generate_checked_copy_v2.py'
with open(filepath, 'r') as f:
    content = f.read()

old_logic = """\
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
                        best_move = moves[0]"""

new_logic = """\
                        dx1 = o_rect[2] - m_rect[0] + 8
                        dx2 = o_rect[0] - m_rect[2] - 8
                        dy1 = o_rect[3] - m_rect[1] + 8
                        dy2 = o_rect[1] - m_rect[3] - 8
                        
                        moves = []
                        if m_type == "stamp":
                            # Stamps move ONLY left/right
                            moves = [
                                (dx1, 0, abs(dx1)),
                                (dx2, 0, abs(dx2)),
                            ]
                        elif m_type == "feedback":
                            # Feedback moves ONLY up/down
                            moves = [
                                (0, dy1, abs(dy1)),
                                (0, dy2, abs(dy2)),
                            ]
                        else:
                            moves = [
                                (dx1, 0, abs(dx1)),
                                (dx2, 0, abs(dx2)),
                                (0, dy1, abs(dy1)),
                                (0, dy2, abs(dy2)),
                            ]
                        
                        moves.sort(key=lambda x: x[2])
                        best_move = moves[0]"""

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Constraints updated successfully.")
else:
    print("Could not find the old logic block.")
