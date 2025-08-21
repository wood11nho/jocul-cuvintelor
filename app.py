import json
import random
import threading
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# Initializam aplicatia Flask si SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-final-revised!'
socketio = SocketIO(app)

# --- Starea Jocului (Game State) ---
game_state = {
    "faza_curenta": "inactiv", # inactiv, asteptare_jucator_nou, confirmare_start_tura, tura_activa, asteptare_validare, cuvant_rezolvat, tura_incheiata, joc_incheiat
    "jucatori": [],
    "scoruri": {},
    "ordine_jucatori": [],
    "jucator_curent_index": -1,
    "cuvinte_de_joc": [],
    "cuvant_curent_index": -1,
    "main_timer": None,
    "answer_timer": None,
    "timp_ramas_main": 240,
    "timp_ramas_answer": 30,
    "cuvant_curent_display": {
        "definitie": "",
        "litere_ghicite": [],
        "valoare_ramasa": 0,
        "cuvant_original": ""
    }
}

# --- Functii Utilitare ---
def load_words():
    """Incarca cuvintele neutilizate din JSON."""
    with open('cuvinte.json', 'r+', encoding='utf-8') as f:
        all_words = json.load(f)
        for word in all_words:
            if 'utilizat' not in word:
                word['utilizat'] = 0
        
        available_words = [w for w in all_words if w.get('utilizat', 0) == 0]
        if len(available_words) < 14:
            for word in all_words:
                word['utilizat'] = 0
            available_words = all_words
            f.seek(0)
            json.dump(all_words, f, indent=4, ensure_ascii=False)
            f.truncate()

    random.shuffle(available_words)
    return available_words[:14]

def update_word_as_used(word_to_mark):
    """Marcheaza un cuvant ca utilizat in fisierul JSON."""
    with open('cuvinte.json', 'r+', encoding='utf-8') as f:
        all_words = json.load(f)
        for word in all_words:
            if word['cuvant'].upper() == word_to_mark.upper():
                word['utilizat'] = 1
                break
        f.seek(0)
        json.dump(all_words, f, indent=4, ensure_ascii=False)
        f.truncate()

def broadcast_game_state():
    """Trimite starea actuala a jocului si starea butoanelor catre toti clientii."""
    faza = game_state["faza_curenta"]
    current_player_name = game_state["ordine_jucatori"][game_state["jucator_curent_index"]] if game_state["jucator_curent_index"] != -1 else ""
    
    stare_butoane = {
        "jucator": {
            "cer_litera": faza == "tura_activa",
            "buton_rosu": faza == "tura_activa"
        },
        "prezentator": {
            "continua": faza in ["asteptare_jucator_nou", "confirmare_start_tura", "cuvant_rezolvat", "tura_incheiata"],
            "validare": faza == "asteptare_validare"
        }
    }

    payload = {
        "jucator_curent": current_player_name,
        "scor": game_state["scoruri"].get(current_player_name, 0),
        "definitie": game_state["cuvant_curent_display"]["definitie"],
        "litere_afisate": game_state["cuvant_curent_display"]["litere_ghicite"],
        "valoare_ramasa": game_state["cuvant_curent_display"]["valoare_ramasa"],
        "timp_ramas_main": game_state["timp_ramas_main"],
        "scoruri_finale": game_state["scoruri"],
        "stare_butoane": stare_butoane
    }
    socketio.emit('update_jucator', payload)

    host_payload = payload.copy()
    host_payload["cuvant"] = game_state["cuvant_curent_display"]["cuvant_original"]
    socketio.emit('update_prezentator', host_payload)

# --- Functii de Timer ---
def main_timer_tick():
    if game_state["faza_curenta"] == "tura_activa" and game_state["timp_ramas_main"] > 0:
        game_state["timp_ramas_main"] -= 1
        socketio.emit('update_timer', {'type': 'main', 'time': game_state["timp_ramas_main"]})
        game_state["main_timer"] = threading.Timer(1.0, main_timer_tick)
        game_state["main_timer"].start()
    elif game_state["faza_curenta"] == "tura_activa":
        game_state["faza_curenta"] = "tura_incheiata"
        socketio.emit('show_message', "Timpul a expirat!")
        broadcast_game_state()

def answer_timer_tick():
    if game_state["faza_curenta"] == "asteptare_validare" and game_state["timp_ramas_answer"] > 0:
        game_state["timp_ramas_answer"] -= 1
        socketio.emit('update_timer', {'type': 'answer', 'time': game_state["timp_ramas_answer"]})
        game_state["answer_timer"] = threading.Timer(1.0, answer_timer_tick)
        game_state["answer_timer"].start()
    elif game_state["faza_curenta"] == "asteptare_validare":
        handle_answer_validation(is_correct=False, from_timeout=True)

# --- Logica Principala a Jocului ---
def start_next_word():
    # Oprim orice timer anterior pentru a evita suprapuneri
    if game_state["main_timer"]: game_state["main_timer"].cancel()

    game_state["cuvant_curent_index"] += 1
    if game_state["cuvant_curent_index"] >= len(game_state["cuvinte_de_joc"]):
        game_state["faza_curenta"] = "tura_incheiata"
        socketio.emit('show_message', "Lista de cuvinte terminata!")
        broadcast_game_state()
        return

    word_data = game_state["cuvinte_de_joc"][game_state["cuvant_curent_index"]]
    cuvant = word_data["cuvant"].upper()
    
    game_state["cuvant_curent_display"] = {
        "definitie": word_data["definitie"],
        "litere_ghicite": ['_' for _ in cuvant],
        "valoare_ramasa": len(cuvant) * 100,
        "cuvant_original": cuvant
    }
    update_word_as_used(cuvant)
    game_state["faza_curenta"] = "tura_activa"
    
    # **FIX:** Repornim timerul principal AICI, de fiecare data cand un cuvant nou incepe
    main_timer_tick()
    broadcast_game_state()

def handle_answer_validation(is_correct, from_timeout=False):
    if game_state["answer_timer"]:
        game_state["answer_timer"].cancel()
    
    current_player_name = game_state["ordine_jucatori"][game_state["jucator_curent_index"]]
    valoare = game_state["cuvant_curent_display"]["valoare_ramasa"]
    cuvant = game_state["cuvant_curent_display"]["cuvant_original"]

    if is_correct:
        game_state["scoruri"][current_player_name] += valoare
        socketio.emit('show_feedback', {"corect": True, "cuvant": cuvant})
    else:
        game_state["scoruri"][current_player_name] -= valoare
        mesaj = "Timpul de raspuns a expirat!" if from_timeout else "Raspuns gresit!"
        socketio.emit('show_feedback', {"corect": False, "cuvant": cuvant, "mesaj": mesaj})

    game_state["faza_curenta"] = "cuvant_rezolvat"
    broadcast_game_state()

def end_game():
    game_state["faza_curenta"] = "joc_incheiat"
    scoruri = game_state["scoruri"]
    if not scoruri:
        winner_message = "Jocul s-a incheiat fara castigatori."
    else:
        castigator = max(scoruri, key=scoruri.get)
        suma_castigata = scoruri[castigator]
        winner_message = f"FELICITARI! Castigatorul este {castigator} cu {suma_castigata} lei!"

    socketio.emit('show_message', winner_message)
    socketio.emit('game_over', {"scoruri": game_state["scoruri"]})
    broadcast_game_state()

# --- Rutele HTTP ---
@app.route('/')
def index(): return render_template('index.html')
@app.route('/joc')
def joc(): return render_template('joc.html')
@app.route('/prezentator')
def prezentator(): return render_template('prezentator.html')

# --- Evenimente Socket.IO ---
@socketio.on('start_game')
def on_start_game(data):
    game_state["jucatori"] = data['players']
    game_state["ordine_jucatori"] = random.sample(game_state["jucatori"], len(game_state["jucatori"]))
    game_state["scoruri"] = {player: 0 for player in game_state["jucatori"]}
    game_state["jucator_curent_index"] = -1
    game_state["faza_curenta"] = "asteptare_jucator_nou"
    broadcast_game_state()
    socketio.emit('show_message', "Joc configurat! Apasati 'Continua' pe ecranul prezentatorului pentru a incepe.")

@socketio.on('next_step')
def on_next_step():
    faza = game_state["faza_curenta"]

    if faza == "asteptare_jucator_nou":
        game_state["jucator_curent_index"] += 1
        if game_state["jucator_curent_index"] >= len(game_state["ordine_jucatori"]):
            end_game()
            return
        
        current_player_name = game_state["ordine_jucatori"][game_state["jucator_curent_index"]]
        socketio.emit('show_message', f"Urmeaza {current_player_name}!")
        
        # **FIX:** Doar anuntam jucatorul si asteptam urmatorul click. Nu pornim timerul.
        game_state["faza_curenta"] = "confirmare_start_tura"
        broadcast_game_state()

    elif faza == "confirmare_start_tura":
        # Acum, la al doilea click, pornim efectiv tura
        game_state["cuvinte_de_joc"] = load_words()
        game_state["cuvant_curent_index"] = -1
        game_state["timp_ramas_main"] = 240
        start_next_word() # Aceasta functie va porni si timerul
        
    elif faza == "cuvant_rezolvat":
        start_next_word()

    elif faza == "tura_incheiata":
        current_player_name = game_state["ordine_jucatori"][game_state["jucator_curent_index"]]
        socketio.emit('show_message', f"Tura lui {current_player_name} s-a incheiat. Scor: {game_state['scoruri'][current_player_name]} lei.")
        game_state["faza_curenta"] = "asteptare_jucator_nou"
        broadcast_game_state()

@socketio.on('request_letter')
def on_request_letter():
    if game_state["faza_curenta"] != "tura_activa": return
    
    cuvant = game_state["cuvant_curent_display"]["cuvant_original"]
    litere_ghicite = game_state["cuvant_curent_display"]["litere_ghicite"]
    
    pozitii_ramase = [i for i, char in enumerate(litere_ghicite) if char == '_']
    if not pozitii_ramase: return

    pozitie_random = random.choice(pozitii_ramase)
    litere_ghicite[pozitie_random] = cuvant[pozitie_random]
    
    game_state["cuvant_curent_display"]["valoare_ramasa"] = max(0, game_state["cuvant_curent_display"]["valoare_ramasa"] - 100)
    broadcast_game_state()

@socketio.on('press_red_button')
def on_press_red_button():
    if game_state["faza_curenta"] != "tura_activa": return
    
    if game_state["main_timer"]:
        game_state["main_timer"].cancel()
    
    game_state["faza_curenta"] = "asteptare_validare"
    game_state["timp_ramas_answer"] = 30
    answer_timer_tick()
    broadcast_game_state()

@socketio.on('host_validation')
def on_host_validation(data):
    if game_state["faza_curenta"] != "asteptare_validare": return
    
    is_correct = data['status'] == 'corect'
    handle_answer_validation(is_correct)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')