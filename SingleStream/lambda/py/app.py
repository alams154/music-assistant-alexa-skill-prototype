from flask import Flask, request, jsonify
from flask_ask_sdk.skill_adapter import SkillAdapter
from lambda_function import sb  # sb is the SkillBuilder from lambda_function.py

app = Flask(__name__)
skill_adapter = SkillAdapter(
    skill=sb.create(), 
    skill_id="<>",  # Replace with your actual skill ID
    app=app)

@app.route("/", methods=["POST"])
def invoke_skill():
    return skill_adapter.dispatch_request()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
