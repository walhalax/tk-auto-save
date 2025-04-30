<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>com.apple.Automator</string>
	<key>WFWorkflowActions</key>
	<array>
		<dict>
			<key>WFActionIdentifier</key>
			<string>com.apple.workflow.actions.runshellscript</string>
			<key>WFActionParameters</key>
			<dict>
				<key>WFShellScriptName</key>
				<string>Run Shell Script</string>
				<key>WFShellScriptString</key>
				<string>cd "/Users/walhalax/Library/Mobile Documents/com~apple~CloudDocs/Coding/VSCode/Project/tk-auto-dl"\nsh start_headless.sh</string>
				<key>WFShellScriptLanguage</key>
				<string>/bin/bash</string>
			</dict>
		</dict>
	</array>
	<key>WFWorkflowIcon</key>
	<dict>
		<key>WFImageName</key>
		<string>AutomatorApp.icns</string>
		<key>WFWorkflowIconType</key>
		<string>com.apple.automator.icon.workflow</string>
	</dict>
	<key>WFWorkflowName</key>
	<string>ヘッドレスモードで起動</string>
</dict>
</plist>