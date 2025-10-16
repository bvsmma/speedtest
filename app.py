import os
import json
import subprocess
from flask import Flask, render_template, request, jsonify
from google import genai
from dotenv import load_dotenv

# Laster miljøvariabler fra .env
load_dotenv()

# =======================================================
# APPLIKASJONSOPPSETT
# =======================================================
app = Flask(__name__)

# Initialisering av Gemini API
# Nøkkelen hentes fra .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Sjekker nøkkelens tilstedeværelse
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY ble ikke funnet i .env-filen. Vennligst legg til nøkkelen din.")
    
ai = genai.Client(api_key=GEMINI_API_KEY)


# =======================================================
# 1. Hovedrute for sidevisning
# =======================================================
@app.route('/')
def index():
    # Flask søker automatisk etter index.html i templates-mappen
    return render_template('index.html')


# =======================================================
# 2. API for å kjøre hastighetstest og Gemini-analyse
# =======================================================
@app.route('/api/run-test', methods=['POST'])
def run_test():
    try:
        data = request.json
        # Standardtekst for brukerkontekst på norsk
        user_context = data.get('context', 'Jeg surfer bare på nettet.')
        
        # --- KJØRER HASTIGHETSTEST ---
        print("Kjører Hastighetstest...")
        
        # 1. KOMMANDO FOR SPEEDTEST
        # Lar speedtest-cli automatisk finne den nærmeste og beste serveren.
        command = ['speedtest', '--json'] 
        
        # Kjører speedtest og henter utdata. Setter timeout til 30 sekunder.
        process = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            check=False,
            timeout=30 
        )
        
        # Håndterer feilkode fra kommandoen
        if process.returncode != 0:
            error_details = f"Kommandoen avsluttet med feil: Kode {process.returncode}. STDOUT: {process.stdout.strip()}. STDERR: {process.stderr.strip()}"
            raise subprocess.CalledProcessError(process.returncode, command, output=process.stdout, stderr=process.stderr)

        
        # 2. PÅLITELIG JSON-UTGANGSBEHANDLING
        
        stdout_lines = process.stdout.strip().splitlines()
        json_output = ""

        # Søker etter den siste linjen som starter med '{'
        for line in reversed(stdout_lines):
            line = line.strip()
            if line.startswith('{'):
                json_output = line
                break
        
        if not json_output:
            raise ValueError(f"Klarte ikke å finne JSON-utdata fra Speedtest. Full utdata (STDOUT): {process.stdout.strip()}. STDERR: {process.stderr.strip()}")

        try:
            # Tolker funnet JSON
            test_data_raw = json.loads(json_output)
        except json.JSONDecodeError as e:
            raise ValueError(f"Feil ved dekoding av JSON: {e}. Mottatt: {json_output}")
            
        # 3. UTREKKING OG FORMATERING AV DATA (verdier i bits/s og ms)
        
        raw_download_bits = test_data_raw.get('download', 0.0)
        raw_upload_bits = test_data_raw.get('upload', 0.0)
        raw_ping_ms = test_data_raw.get('ping', 0.0)
        
        # Formatering av Upload 
        upload = f"{round(raw_upload_bits / 1000000, 2)} Mbit/s"
        
        # Håndtering av Download (hvis 0.0 eller mindre)
        if raw_download_bits <= 0.0:
            download = "Utilgjengelig"
        else:
            download = f"{round(raw_download_bits / 1000000, 2)} Mbit/s"
            
        # Håndtering av Ping (hvis urealistisk høy)
        if raw_ping_ms > 10000 or raw_ping_ms <= 0.0:
            ping = "Feil/For høy"
        else:
            ping = f"{round(raw_ping_ms, 0)} ms"

        # Samler data for Gemini
        test_data = {
            'download': download,
            'upload': upload,
            'ping': ping,
            'context': user_context
        }
        
        print('Testresultater:', test_data)

        # --- GENERERING AV GEMINI-PROMPT (med krav om ren HTML) ---
        prompt = f"""
            Analyser følgende resultater fra internetthastighetstesten og gi en nyttig rapport.
            
            VELDIG VIKTIG REGEL: Generer svaret ved å kun bruke ren HTML-kode, egnet for innsetting i en HTML-blokk (div). Bruk avsnittstagger (<p>), linjeskift (<br>) og fet skrift (<b>) for utheving. Ikke bruk Markdown (ingen **, # eller andre formateringstegn).
            
            1. Avgjør om denne hastigheten passer for konteksten gitt av brukeren.
            2. Gi to-tre konkrete anbefalinger for hvordan tilkoblingen kan forbedres eller optimaliseres basert på indikatorene (spesielt Ping og Nedlasting).
            3. Hvis hastigheten er veldig lav, foreslå en tekst som kan sendes til internettleverandøren.
            
            Data:
            - Nedlastingshastighet (Download): {download}
            - Opplastingshastighet (Upload): {upload}
            - Ping: {ping}
            - Brukerkontekst: {user_context}
        """
        
        # --- FORESPØRSEL TIL GEMINI API ---
        response = ai.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        gemini_report = response.text
        
        # Sender testresultater og analyse fra Gemini tilbake
        return jsonify({
            'success': True,
            'data': test_data,
            'analysis': gemini_report
        })

    except subprocess.CalledProcessError as e:
        error_msg = f"Feil ved kjøring av Speedtest. Returkode: {e.returncode}. STDOUT: {e.output.strip()}. STDERR: {e.stderr.strip()}"
        print(error_msg)
        return jsonify({'success': False, 'message': f'Kritisk Speedtest-feil. Sjekk installasjonen. {error_msg}'}), 500
    except subprocess.TimeoutExpired:
        print("Feil: Speedtest fullførte ikke innen 30 sekunder.")
        return jsonify({'success': False, 'message': 'Feil: Hastighetstesten fullførte ikke innen 30 sekunder. Prøv igjen.'}), 500
    except ValueError as e:
        # Feil generert under JSON-behandling
        print(f"En serverfeil oppstod (JSON-behandling): {e}")
        return jsonify({'success': False, 'message': f'Serverfeil ved behandling av Speedtest-resultater: {str(e)}'}), 500
    except Exception as e:
        print(f"En uforutsett serverfeil oppstod: {e}")
        return jsonify({'success': False, 'message': f'En uforutsett feil oppstod på serveren: {str(e)}'}), 500

if __name__ == '__main__':
    # Starter Flask-serveren
    app.run(debug=True, port=3000)
