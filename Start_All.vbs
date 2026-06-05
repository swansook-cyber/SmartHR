Option Explicit

Dim shell, fso, projectDir, pythonCmd, ngrokCmd
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonCmd = FindPythonCommand()
ngrokCmd = FindNgrokCommand()

If pythonCmd = "" Then
    MsgBox "Cannot find Python. Please install Python or add python.exe to PATH.", vbCritical, "SmartHR Launcher"
    WScript.Quit 1
End If

If ngrokCmd = "" Then
    MsgBox "Cannot find ngrok.exe in this folder or PATH.", vbCritical, "SmartHR Launcher"
    WScript.Quit 1
End If

RunService "HRMS_Backend", pythonCmd & " -m uvicorn main:app --host 0.0.0.0 --port 8000"
WScript.Sleep 3000

RunService "HRMS_Frontend", pythonCmd & " -m streamlit run frontend.py --server.address 0.0.0.0 --server.port 8501"
WScript.Sleep 5000

RunService "HRMS_Ngrok", ngrokCmd & " http --domain=unsilicified-uncorseted-marybelle.ngrok-free.dev 8501"
WScript.Sleep 2000

shell.Run "http://localhost:8501", 1, False

Sub RunService(windowTitle, commandText)
    Dim fullCommand
    fullCommand = "cmd /c cd /d " & Q(projectDir) & " && " & commandText
    shell.Run fullCommand, 0, False
End Sub

Function FindPythonCommand()
    Dim cmd

    cmd = FirstWhereResult("py.exe", True)
    If cmd <> "" Then
        FindPythonCommand = Q(cmd) & " -3"
        Exit Function
    End If

    cmd = FirstWhereResult("python.exe", False)
    If cmd <> "" Then
        FindPythonCommand = Q(cmd)
        Exit Function
    End If

    cmd = FirstExistingFile(Array( _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python314\python.exe", _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\python.exe", _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\python.exe", _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python311\python.exe", _
        shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python310\python.exe", _
        "C:\Program Files\Python314\python.exe", _
        "C:\Program Files\Python313\python.exe", _
        "C:\Program Files\Python312\python.exe", _
        "C:\Program Files\Python311\python.exe", _
        "C:\Program Files\Python310\python.exe" _
    ))

    If cmd <> "" Then
        FindPythonCommand = Q(cmd)
    Else
        FindPythonCommand = ""
    End If
End Function

Function FindNgrokCommand()
    Dim localNgrok, cmd

    localNgrok = fso.BuildPath(projectDir, "ngrok.exe")
    If fso.FileExists(localNgrok) Then
        FindNgrokCommand = Q(localNgrok)
        Exit Function
    End If

    cmd = FirstWhereResult("ngrok.exe", False)
    If cmd <> "" Then
        FindNgrokCommand = Q(cmd)
    Else
        FindNgrokCommand = ""
    End If
End Function

Function FirstWhereResult(exeName, allowWindowsApps)
    On Error Resume Next

    Dim execObj, line
    Set execObj = shell.Exec("cmd /c where " & exeName)

    If Err.Number <> 0 Then
        Err.Clear
        FirstWhereResult = ""
        On Error GoTo 0
        Exit Function
    End If

    Do Until execObj.StdOut.AtEndOfStream
        line = Trim(execObj.StdOut.ReadLine)
        If line <> "" And fso.FileExists(line) Then
            If allowWindowsApps Or InStr(1, line, "\Microsoft\WindowsApps\", vbTextCompare) = 0 Then
                FirstWhereResult = line
                On Error GoTo 0
                Exit Function
            End If
        End If
    Loop

    FirstWhereResult = ""
    On Error GoTo 0
End Function

Function FirstExistingFile(candidates)
    Dim item
    For Each item In candidates
        If fso.FileExists(item) Then
            FirstExistingFile = item
            Exit Function
        End If
    Next
    FirstExistingFile = ""
End Function

Function Q(value)
    Q = Chr(34) & value & Chr(34)
End Function
