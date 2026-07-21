# How to Run CheckerAI on Windows

This guide is designed for a completely fresh Windows computer. You do NOT need any programming experience or developer tools (like Python or Node.js) to run this application!

## Step 1: Install Docker Desktop
The entire application (Database, Backends, and Frontend) runs inside isolated containers using a tool called Docker.
1. Go to [https://docs.docker.com/desktop/install/windows-install/](https://docs.docker.com/desktop/install/windows-install/) and download **Docker Desktop for Windows**.
2. Run the installer and keep all default settings (ensure WSL 2 backend is selected if prompted).
3. Restart your computer if required.
4. Open the **Docker Desktop** app and leave it running in the background.

## Step 2: Download the Project
If you haven't already:
1. Go to this project's GitHub page.
2. Click the green **Code** button and select **Download ZIP**.
3. Extract the ZIP file to a folder on your computer (e.g., your Desktop or Documents folder).

*(Note: Ensure that the `All_Paper_JSONs` folder is inside this extracted directory).*

## Step 3: Add your API Keys
1. Open the extracted `CheckerAI` folder.
2. Find the file named `.env.example`.
3. Rename this file to `.env` (just `.env`, nothing else). If Windows hides the file extension, you can open it in Notepad, paste your OpenAI API key replacing `YOUR_API_KEY_HERE`, and save it as "All Files" with the name `.env`.

## Step 4: Start the Application!
1. Open the **Command Prompt** (press the Windows key, type `cmd`, and hit Enter).
2. Type `cd ` followed by the path to your extracted folder and press Enter. (For example: `cd Desktop\CheckerAI`).
3. Type the following command and press Enter:
   ```cmd
   docker compose up -d
   ```
4. Docker will now download the necessary components and build the application. This might take 5-10 minutes the very first time. You will know it's done when it says all containers are "Started".

## Step 5: Open the App
1. Open your web browser (Chrome, Edge, etc.).
2. Go to: **[http://localhost](http://localhost)**
3. The CheckerAI frontend will open automatically! All your marking, uploading, and exam configurations are fully connected to your local APIs out of the box.
