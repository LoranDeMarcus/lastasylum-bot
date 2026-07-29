' Тихий запуск Last Asylum Bot — без окна консоли (только GUI).
' Используй, когда всё уже откалибровано и ошибки на старте не ожидаются.
Set fso = CreateObject("Scripting.FileSystemObject")
projDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = projDir
' pythonw.exe = без консоли; 0 = скрытое окно процесса
sh.Run """" & projDir & "\.venv\Scripts\pythonw.exe"" -m src.app", 0, False
