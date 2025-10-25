#!/usr/bin/env python3
# p2p_chess.py
# Single-file Tkinter GUI for P2P chess with AI/LLM hook (std lib only).

import tkinter as tk
from tkinter import messagebox
import socket
import threading
import json
import sys
import argparse
import time
from typing import Optional, Tuple, List

# ============== Chess Core ==============

FILES = "abcdefgh"
RANKS = "12345678"

def in_bounds(r, c):
    return 0 <= r < 8 and 0 <= c < 8

def algebraic(r, c):
    return f"{FILES[c]}{RANKS[7-r]}"

def parse_square(sq):
    # e.g. "e2" -> (row, col)
    if len(sq) != 2 or sq[0] not in FILES or sq[1] not in RANKS:
        return None
    c = FILES.index(sq[0])
    r = 7 - RANKS.index(sq[1])
    return (r, c)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

class Board:
    def __init__(self):
        self.board = self.load_fen(START_FEN)
        self.white_to_move = True
        self.castling = {"K": True, "Q": True, "k": True, "q": True}
        self.en_passant = None
        self.halfmove = 0
        self.fullmove = 1
        self.history = []
        self.captured = []

    def load_fen(self, fen):
        rows = fen.split()[0].split("/")
        board = [[None]*8 for _ in range(8)]
        for r, row in enumerate(rows):
            c = 0
            for ch in row:
                if ch.isdigit():
                    c += int(ch)
                else:
                    board[r][c] = ch
                    c += 1
        return board

    def piece_color(self, p):
        if p is None: return None
        return 'w' if p.isupper() else 'b'

    def is_white(self): return self.white_to_move
    def turn_color(self): return 'w' if self.white_to_move else 'b'

    def squares_attacked_by(self, color):
        # Basic attack map (no pins resolution for speed)
        attacks = set()
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if not p or self.piece_color(p) != color:
                    continue
                for (rr, cc) in self.pseudo_moves_from(r, c, p, captures_only=True):
                    attacks.add((rr, cc))
        return attacks

    def king_pos(self, color):
        target = 'K' if color=='w' else 'k'
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == target:
                    return (r, c)
        return None

    def in_check(self, color):
        kp = self.king_pos(color)
        if kp is None: return False
        opp = 'b' if color=='w' else 'w'
        return kp in self.squares_attacked_by(opp)

    def line_moves(self, r, c, deltas, captures_only=False):
        res = []
        color = self.piece_color(self.board[r][c])
        for dr, dc in deltas:
            rr, cc = r+dr, c+dc
            while in_bounds(rr, cc):
                target = self.board[rr][cc]
                if target is None:
                    if not captures_only:
                        res.append((rr, cc))
                else:
                    if self.piece_color(target) != color:
                        res.append((rr, cc))
                    break
                rr += dr; cc += dc
        return res

    def pseudo_moves_from(self, r, c, p, captures_only=False):
        res = []
        color = self.piece_color(p)
        if p is None: return res
        if p.lower() == 'p':
            dir = -1 if color=='w' else 1
            start_rank = 6 if color=='w' else 1
            # forward
            if not captures_only:
                nr = r+dir
                if in_bounds(nr,c) and self.board[nr][c] is None:
                    res.append((nr,c))
                    nr2 = r+2*dir
                    if r==start_rank and self.board[nr2][c] is None:
                        res.append((nr2,c))
            # captures
            for dc in (-1,1):
                nr, nc = r+dir, c+dc
                if in_bounds(nr,nc):
                    t = self.board[nr][nc]
                    if t and self.piece_color(t) != color:
                        res.append((nr,nc))
                    # en passant
                    if self.en_passant == (nr, nc):
                        res.append((nr,nc))
        elif p.lower() == 'n':
            for dr, dc in [(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]:
                nr, nc = r+dr, c+dc
                if in_bounds(nr,nc):
                    t = self.board[nr][nc]
                    if t is None and not captures_only:
                        res.append((nr,nc))
                    elif t and self.piece_color(t) != color:
                        res.append((nr,nc))
        elif p.lower() == 'b':
            res += self.line_moves(r,c,[(1,1),(1,-1),(-1,1),(-1,-1)], captures_only)
        elif p.lower() == 'r':
            res += self.line_moves(r,c,[(1,0),(-1,0),(0,1),(0,-1)], captures_only)
        elif p.lower() == 'q':
            res += self.line_moves(r,c,[(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)], captures_only)
        elif p.lower() == 'k':
            for dr in (-1,0,1):
                for dc in (-1,0,1):
                    if dr==0 and dc==0: continue
                    nr, nc = r+dr, c+dc
                    if in_bounds(nr,nc):
                        t = self.board[nr][nc]
                        if t is None and not captures_only:
                            res.append((nr,nc))
                        elif t and self.piece_color(t) != color:
                            res.append((nr,nc))
            # Castling (simplified: no check-through validation beyond attack map)
            if not captures_only:
                colorK = 'K' if color=='w' else 'k'
                start_row = 7 if color=='w' else 0
                king_side = ('K' if color=='w' else 'k') in self.castling and self.castling['K' if color=='w' else 'k']
                queen_side = ('Q' if color=='w' else 'q') in self.castling and self.castling['Q' if color=='w' else 'q']
                if r==start_row and c==4 and self.board[r][c]==colorK:
                    # King side
                    if king_side and self.board[r][5] is None and self.board[r][6] is None and self.board[r][7] in ('R' if color=='w' else 'r'):
                        res.append((r,6))
                    # Queen side
                    if queen_side and self.board[r][3] is None and self.board[r][2] is None and self.board[r][1] is None and self.board[r][0] in ('R' if color=='w' else 'r'):
                        res.append((r,2))
        return res

    def legal_moves_from(self, r, c):
        p = self.board[r][c]
        color = self.piece_color(p)
        if p is None or color != self.turn_color():
            return []
        candidates = self.pseudo_moves_from(r, c, p)
        legal = []
        for (nr, nc) in candidates:
            if self.is_legal_move((r,c),(nr,nc)):
                legal.append((nr,nc))
        return legal

    def is_legal_move(self, src, dst):
        r,c = src; nr,nc = dst
        p = self.board[r][c]
        if p is None or self.piece_color(p) != self.turn_color():
            return False
        if (nr,nc) not in self.pseudo_moves_from(r,c,p):
            return False
        # simulate
        saved = self._snapshot()
        self._apply_move_basic(src, dst)
        illegal = self.in_check(self.turn_color())  # after move, turn hasn't toggled yet
        self._restore(saved)
        return not illegal

    def _snapshot(self):
        return {
            "board":[row[:] for row in self.board],
            "white_to_move": self.white_to_move,
            "castling": self.castling.copy(),
            "en_passant": self.en_passant,
            "halfmove": self.halfmove,
            "fullmove": self.fullmove,
            "history": self.history[:],
            "captured": self.captured[:],
        }

    def _restore(self, snap):
        self.board = [row[:] for row in snap["board"]]
        self.white_to_move = snap["white_to_move"]
        self.castling = snap["castling"].copy()
        self.en_passant = snap["en_passant"]
        self.halfmove = snap["halfmove"]
        self.fullmove = snap["fullmove"]
        self.history = snap["history"][:]
        self.captured = snap["captured"][:]

    def _apply_move_basic(self, src, dst, promotion=None):
        r,c = src; nr,nc = dst
        p = self.board[r][c]
        target = self.board[nr][nc]
        # Castling handling
        if p in ('K','k') and c==4 and (nc==6 or nc==2) and r in (7,0):
            if nc==6:  # king side
                self.board[r][6] = p
                self.board[r][5] = self.board[r][7]
                self.board[r][4] = None
                self.board[r][7] = None
            else:      # queen side
                self.board[r][2] = p
                self.board[r][3] = self.board[r][0]
                self.board[r][4] = None
                self.board[r][0] = None
        else:
            # en passant capture
            if p in ('P','p') and self.en_passant == (nr,nc) and target is None:
                dir = -1 if p=='P' else 1
                self.board[nr - dir][nc] = None
            # normal move
            self.board[nr][nc] = p
            self.board[r][c] = None

        # update en passant
        self.en_passant = None
        if p in ('P','p') and abs(nr - r) == 2:
            self.en_passant = ( (r+nr)//2, c )

        # promotion
        if p == 'P' and nr == 0:
            self.board[nr][nc] = promotion or 'Q'
        elif p == 'p' and nr == 7:
            self.board[nr][nc] = promotion or 'q'

        # castling rights update
        if p == 'K':
            self.castling['K'] = False; self.castling['Q'] = False
        if p == 'k':
            self.castling['k'] = False; self.castling['q'] = False
        if r==7 and c==7 and self.board[7][7] != 'R': self.castling['K'] = False
        if r==7 and c==0 and self.board[7][0] != 'R': self.castling['Q'] = False
        if r==0 and c==7 and self.board[0][7] != 'r': self.castling['k'] = False
        if r==0 and c==0 and self.board[0][0] != 'r': self.castling['q'] = False

        # halfmove clock
        if target or p.lower() == 'p':
            self.halfmove = 0
            if target:
                self.captured.append(target)
        else:
            self.halfmove += 1

    def move(self, src, dst, promotion=None):
        if not self.is_legal_move(src, dst):
            return False
        self._apply_move_basic(src, dst, promotion)
        san = f"{self.piece_to_letter(self.board[dst[0]][dst[1]])}{algebraic(*dst)}"
        self.history.append(san)
        # toggle turn
        self.white_to_move = not self.white_to_move
        if not self.white_to_move:
            self.fullmove += 1
        return True

    def piece_to_letter(self, p):
        if p is None: return ''
        base = p.upper()
        return '' if base=='P' else base

    def legal_moves(self):
        allm = []
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p and self.piece_color(p) == self.turn_color():
                    for d in self.legal_moves_from(r,c):
                        allm.append(((r,c),d))
        return allm

    def is_checkmate(self):
        if not self.in_check(self.turn_color()): return False
        return len(self.legal_moves()) == 0

    def is_stalemate(self):
        if self.in_check(self.turn_color()): return False
        return len(self.legal_moves()) == 0

# ============== Networking (P2P) ==============

class Peer:
    def __init__(self, host: Optional[str], port: int, join: Optional[str]):
        self.sock = None
        self.listener = None
        self.is_server = host is not None and join is None
        self.host = host
        self.port = port
        self.join_addr = join
        self.on_message = None
        self.connected = False

    def start(self):
        if self.is_server:
            self.listener = threading.Thread(target=self._server_thread, daemon=True)
            self.listener.start()
        elif self.join_addr:
            t = threading.Thread(target=self._client_thread, daemon=True)
            t.start()

    def _server_thread(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(1)
        conn, addr = s.accept()
        self.sock = conn
        self.connected = True
        self._recv_loop()

    def _client_thread(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        while True:
            try:
                s.connect((self.join_addr, self.port))
                break
            except Exception:
                time.sleep(0.5)
        self.sock = s
        self.connected = True
        self._recv_loop()

    def send(self, obj):
        if not self.connected or not self.sock:
            return
        data = json.dumps(obj).encode("utf-8") + b"\n"
        try:
            self.sock.sendall(data)
        except Exception:
            self.connected = False

    def _recv_loop(self):
        buf = b""
        while self.connected:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    self.connected = False
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        obj = json.loads(line.decode("utf-8"))
                        if self.on_message:
                            self.on_message(obj)
                    except Exception:
                        pass
            except Exception:
                self.connected = False
                break

# ============== AI / LLM Hook ==============

def choose_ai_move(board: Board) -> Optional[Tuple[Tuple[int,int], Tuple[int,int]]]:
    # Simple baseline: material-aware random; replace with LLM/engine hook.
    legal = board.legal_moves()
    if not legal: return None
    # Lightweight heuristic: prefer captures and checks
    best = []
    current_color = board.turn_color()

    # Score pieces
    val = {'p':1,'n':3,'b':3,'r':5,'q':9,'k':0}
    def score_move(m):
        (r,c), (nr,nc) = m
        target = board.board[nr][nc]
        s = 0
        if target:
            s += val[target.lower()]
        # center preference
        if 2 <= nr <= 5 and 2 <= nc <= 5:
            s += 0.2
        # try check
        snap = board._snapshot()
        board._apply_move_basic((r,c),(nr,nc))
        will_check = board.in_check('b' if current_color=='w' else 'w')
        board._restore(snap)
        if will_check: s += 0.5
        return s

    scored = sorted(legal, key=score_move, reverse=True)
    return scored[0] if scored else None

# Stub to integrate an LLM:
# def choose_ai_move_llm(board: Board) -> Optional[Tuple[Tuple[int,int], Tuple[int,int]]]:
#     state = export_fen(board)  # implement FEN export if needed
#     prompt = f"Choose the best move for {board.turn_color()} in FEN: {state}. Return in UCI."
#     # Send to your LLM endpoint and parse UCI to ((r,c),(nr,nc))
#     return uci_to_move(uci_str)

# ============== GUI ==============

SQUARE_SIZE = 64
PIECES_UNICODE = {
    'K':'\u2654','Q':'\u2655','R':'\u2656','B':'\u2657','N':'\u2658','P':'\u2659',
    'k':'\u265A','q':'\u265B','r':'\u265C','b':'\u265D','n':'\u265E','p':'\u265F'
}

class App:
    def __init__(self, root, args):
        self.root = root
        self.root.title("P2P Chess + AI")
        self.board = Board()
        self.peer = Peer(args.host, args.port, args.join)
        self.peer.on_message = self.on_peer_message
        self.peer.start()

        self.local_is_white = True if args.host or args.ai else False
        if args.join: self.local_is_white = False
        self.vs_ai = args.ai

        self.canvas = tk.Canvas(root, width=8*SQUARE_SIZE, height=8*SQUARE_SIZE)
        self.canvas.grid(row=0, column=0, padx=8, pady=8)
        self.canvas.bind("<Button-1>", self.on_click)

        self.info = tk.Label(root, text="Status: Ready")
        self.info.grid(row=1, column=0, sticky="we", padx=8)

        self.moves_list = tk.Listbox(root, height=10)
        self.moves_list.grid(row=0, column=1, padx=8, pady=8, sticky="ns")

        self.controls = tk.Frame(root)
        self.controls.grid(row=1, column=1, sticky="we")
        tk.Button(self.controls, text="New game", command=self.new_game).grid(row=0, column=0, padx=4)
        tk.Button(self.controls, text="Offer draw", command=self.offer_draw).grid(row=0, column=1, padx=4)
        tk.Button(self.controls, text="Resign", command=self.resign).grid(row=0, column=2, padx=4)

        self.selected: Optional[Tuple[int,int]] = None
        self.highlight: List[Tuple[int,int]] = []
        self.draw_board()
        self.update_status()
        self.try_ai_turn()

    def new_game(self):
        self.board = Board()
        self.moves_list.delete(0, tk.END)
        self.selected = None
        self.highlight = []
        self.draw_board()
        self.update_status()
        self.peer.send({"type":"new"})
        self.try_ai_turn()

    def offer_draw(self):
        self.peer.send({"type":"draw_offer"})
        messagebox.showinfo("Draw", "Offered draw to opponent.")

    def resign(self):
        self.peer.send({"type":"resign"})
        messagebox.showinfo("Resign", "You resigned.")
        self.root.quit()

    def draw_board(self):
        self.canvas.delete("all")
        for r in range(8):
            for c in range(8):
                x0 = c*SQUARE_SIZE; y0 = r*SQUARE_SIZE
                color = "#f0d9b5" if (r+c)%2==0 else "#b58863"
                self.canvas.create_rectangle(x0, y0, x0+SQUARE_SIZE, y0+SQUARE_SIZE, fill=color, outline="")
                if (r,c) in self.highlight:
                    self.canvas.create_rectangle(x0, y0, x0+SQUARE_SIZE, y0+SQUARE_SIZE, outline="#ff0", width=3)
                p = self.board.board[r][c]
                if p:
                    self.canvas.create_text(x0+SQUARE_SIZE//2, y0+SQUARE_SIZE//2,
                                            text=PIECES_UNICODE[p], font=("Arial", 32))
        # Rank/file labels
        for c in range(8):
            self.canvas.create_text(c*SQUARE_SIZE+8, 8, text=FILES[c], anchor="nw", fill="#333", font=("Arial", 10))
        for r in range(8):
            self.canvas.create_text(8, r*SQUARE_SIZE+SQUARE_SIZE-12, text=RANKS[7-r], anchor="sw", fill="#333", font=("Arial", 10))

    def update_status(self, extra=""):
        t = "White" if self.board.white_to_move else "Black"
        conn = "Connected" if self.peer.connected else "Connecting..."
        status = f"Turn: {t} | {conn}"
        if extra: status += f" | {extra}"
        self.info.config(text=status)

    def on_click(self, event):
        r = event.y // SQUARE_SIZE
        c = event.x // SQUARE_SIZE
        if not in_bounds(r,c): return

        # Enforce side
        if self.board.turn_color() == 'w' and not self.local_is_white and not self.vs_ai: return
        if self.board.turn_color() == 'b' and self.local_is_white and not self.vs_ai: return

        if self.selected is None:
            p = self.board.board[r][c]
            if p and self.board.piece_color(p) == self.board.turn_color():
                self.selected = (r,c)
                self.highlight = self.board.legal_moves_from(r,c)
        else:
            src = self.selected
            dst = (r,c)
            if self.board.move(src, dst):
                self.moves_list.insert(tk.END, f"{algebraic(*src)}-{algebraic(*dst)}")
                self.peer.send({"type":"move","src":src,"dst":dst})
                self.selected = None
                self.highlight = []
                self.draw_board()
                self.update_status()
                self.post_move_checks()
                self.try_ai_turn()
            else:
                # reset selection
                self.selected = None
                self.highlight = []
        self.draw_board()

    def post_move_checks(self):
        if self.board.is_checkmate():
            winner = "Black" if self.board.white_to_move else "White"
            messagebox.showinfo("Checkmate", f"{winner} wins!")
        elif self.board.is_stalemate():
            messagebox.showinfo("Stalemate", "Draw by stalemate.")

    def on_peer_message(self, obj):
        t = obj.get("type")
        if t == "move":
            src = tuple(obj["src"]); dst = tuple(obj["dst"])
            if self.board.move(src, dst):
                self.moves_list.insert(tk.END, f"{algebraic(*src)}-{algebraic(*dst)}")
                self.draw_board()
                self.update_status()
                self.post_move_checks()
                self.try_ai_turn()
        elif t == "new":
            self.new_game()
        elif t == "draw_offer":
            if messagebox.askyesno("Draw offer", "Accept draw?"):
                messagebox.showinfo("Draw", "Game drawn.")
        elif t == "resign":
            messagebox.showinfo("Opponent resigned", "You win!")
            self.root.quit()

    def try_ai_turn(self):
        if not self.vs_ai:
            return
        # AI plays the opposite color of local
        ai_color = 'b' if self.local_is_white else 'w'
        if self.board.turn_color() != ai_color:
            return
        self.update_status("AI thinking...")
        self.root.after(10, self._ai_move_async)

    def _ai_move_async(self):
        def worker():
            m = choose_ai_move(self.board)
            time.sleep(0.25)  # tiny delay for UX
            self.root.after(0, lambda: self._apply_ai_move(m))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_ai_move(self, m):
        if not m:
            messagebox.showinfo("Result", "AI has no legal moves.")
            return
        src, dst = m
        if self.board.move(src, dst):
            self.moves_list.insert(tk.END, f"AI: {algebraic(*src)}-{algebraic(*dst)}")
            self.draw_board()
            self.update_status()
            self.post_move_checks()

# ============== CLI ==============

def parse_args():
    ap = argparse.ArgumentParser(description="P2P Chess + AI (Tkinter)")
    ap.add_argument("--host", help="Host address to listen on (server mode). Example: 0.0.0.0", default=None)
    ap.add_argument("--join", help="Join peer address (client mode). Example: 192.168.1.10", default=None)
    ap.add_argument("--port", help="TCP port", type=int, default=5000)
    ap.add_argument("--ai", help="Play versus local AI", action="store_true")
    return ap.parse_args()

def main():
    args = parse_args()
    root = tk.Tk()
    App(root, args)
    root.mainloop()

if __name__ == "__main__":
    main()
