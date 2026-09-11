Attribute VB_Name = "mdlReport"
Option Explicit

' =============================================================================
' Module  : mdlReport
' Project : FULCRUM Campaign Performance & P&L Analyser
' Purpose : Two public macros for the COVER sheet buttons.
'
'   GenerateCampaignReport  — snapshots the current assumption set, builds
'     a timestamped summary sheet (_REPORT_YYYYMMDD_HHMMSS), exports to PDF
'     in the same folder as the workbook, then locks the sheet.
'
'   ResetToPointEstimates   — writes the five published point-estimate values
'     back to the ASM_ named ranges on INPUTS.
'
' Named ranges required (Formulas → Name Manager, workbook scope):
'   Inputs   : ASM_COST, ASM_BALANCE, ASM_NIM, ASM_TENOR, ASM_RETENTION
'   Outputs  : DRV_T1_MPPC, DRV_T2_MPPC, DRV_T3_MPPC,
'              OUT_VOT_T1T2, OUT_GP_T1T2, OUT_RECOMMENDATION
'   Bounds   : MIN_COST, MAX_COST  (MIN_*/MAX_* for each ASM_ — used only
'              by RunSensitivity in mdlSensitivity, not here)
'
' Button wiring on COVER sheet:
'   "Generate Report"   → GenerateCampaignReport
'   "Reset to Defaults" → ResetToPointEstimates
'
' Import this file: VBE → File → Import File, or drag into the Project window.
' =============================================================================


' ── Point-estimate constants — mirror config/pnl_assumptions.yml ─────────────
' If the YAML baseline changes, update these constants and re-protect INPUTS.
Private Const PE_COST      As Double = 2.5
Private Const PE_BALANCE   As Double = 10000#
Private Const PE_NIM       As Double = 0.015
Private Const PE_TENOR     As Double = 1#
Private Const PE_RETENTION As Double = 0.5

' Sheet protection password. Empty string = protection without a password.
' Change here and re-apply Protect calls if a password is later required.
Private Const SHEET_PWD As String = ""

' Report layout constants — row numbers for each content block.
' Centralised here so the layout can be adjusted without hunting through code.
Private Const RPT_ROW_TITLE   As Long = 1
Private Const RPT_ROW_ASM_HDR As Long = 3
Private Const RPT_ROW_ASM1    As Long = 4   ' Cost per contact
Private Const RPT_ROW_ASM2    As Long = 5   ' Balance
Private Const RPT_ROW_ASM3    As Long = 6   ' NIM
Private Const RPT_ROW_ASM4    As Long = 7   ' Tenor
Private Const RPT_ROW_ASM5    As Long = 8   ' Retention
Private Const RPT_ROW_MET_HDR As Long = 10
Private Const RPT_ROW_MET1    As Long = 11  ' MPPC T1
Private Const RPT_ROW_MET2    As Long = 12  ' MPPC T2
Private Const RPT_ROW_MET3    As Long = 13  ' MPPC T3
Private Const RPT_ROW_MET4    As Long = 14  ' VoT T1+T2
Private Const RPT_ROW_MET5    As Long = 15  ' GP T1+T2
Private Const RPT_ROW_REC_HDR As Long = 17
Private Const RPT_ROW_REC     As Long = 18
Private Const RPT_ROW_FOOTER  As Long = 20

' Blue used for the title and section banners.
Private Const CLR_BRAND  As Long = 2040350  ' RGB(31, 73, 125) — pre-computed
Private Const CLR_WHITE  As Long = 16777215 ' RGB(255, 255, 255)
Private Const CLR_GREY   As Long = 15921906 ' RGB(242, 242, 242) — alternate row
Private Const CLR_TEXT   As Long = 2171169  ' RGB(33, 33, 33) — near-black
Private Const CLR_SUBTLE As Long = 8553090  ' RGB(130, 130, 130) — footer


' =============================================================================
' GenerateCampaignReport  (Public — wired to COVER "Generate Report" button)
' =============================================================================
Public Sub GenerateCampaignReport()

    On Error GoTo ErrHandler

    ' ── Preserve and modify application state ─────────────────────────────────
    Dim bScreenWasOn  As Boolean
    Dim bAlertsWereOn As Boolean
    bScreenWasOn  = Application.ScreenUpdating
    bAlertsWereOn = Application.DisplayAlerts
    Application.ScreenUpdating = False

    ' ── Guard: workbook must be saved so we know where to write the PDF ───────
    If Len(ThisWorkbook.Path) = 0 Then
        Application.ScreenUpdating = bScreenWasOn
        MsgBox "Save the workbook to a folder before generating a report." & _
               vbCrLf & "(The PDF is written beside the .xlsm file.)", _
               vbExclamation, "FULCRUM"
        Exit Sub
    End If

    ' ── Build timestamp strings ───────────────────────────────────────────────
    Dim dtNow         As Date
    Dim sStamp        As String  ' YYYYMMDD_HHMMSS — sheet name and filename
    Dim sStampDisplay As String  ' readable form for the report title row
    dtNow         = Now()
    sStamp        = Format(dtNow, "yyyymmdd_hhmmss")
    sStampDisplay = Format(dtNow, "dd mmm yyyy  hh:mm:ss")

    ' Underscore prefix keeps report tabs sorted to the left of the tab bar.
    Dim sRptName As String
    sRptName = "_REPORT_" & sStamp

    ' ── Force recalculation before reading any output cells ───────────────────
    ' MDL_ named ranges (INDEX/MATCH formulas) and DRV_ cells must reflect the
    ' latest ASM_ inputs before we snapshot them into the report.
    ThisWorkbook.Calculate

    ' ── Read assumption inputs via named ranges ───────────────────────────────
    ' Evaluate resolves both simple cell references (ASM_) and formula-based
    ' names (MDL_ INDEX/MATCH), and works regardless of whether the source
    ' sheet is visible — SCENARIOS and PNL can be hidden without issue.
    ' CDbl converts the Variant returned by Evaluate to an explicit Double.
    Dim dCost      As Double
    Dim dBalance   As Double
    Dim dNIM       As Double
    Dim dTenor     As Double
    Dim dRetention As Double
    dCost      = CDbl(ThisWorkbook.Evaluate("ASM_COST"))
    dBalance   = CDbl(ThisWorkbook.Evaluate("ASM_BALANCE"))
    dNIM       = CDbl(ThisWorkbook.Evaluate("ASM_NIM"))
    dTenor     = CDbl(ThisWorkbook.Evaluate("ASM_TENOR"))
    dRetention = CDbl(ThisWorkbook.Evaluate("ASM_RETENTION"))

    ' ── Read headline metrics ─────────────────────────────────────────────────
    Dim dMppcT1 As Double
    Dim dMppcT2 As Double
    Dim dMppcT3 As Double
    Dim dVoT    As Double
    Dim dGpT1T2 As Double
    dMppcT1 = CDbl(ThisWorkbook.Evaluate("DRV_T1_MPPC"))
    dMppcT2 = CDbl(ThisWorkbook.Evaluate("DRV_T2_MPPC"))
    dMppcT3 = CDbl(ThisWorkbook.Evaluate("DRV_T3_MPPC"))
    dVoT    = CDbl(ThisWorkbook.Evaluate("OUT_VOT_T1T2"))
    dGpT1T2 = CDbl(ThisWorkbook.Evaluate("OUT_GP_T1T2"))

    ' ── Read recommendation text from SUMMARY sheet ───────────────────────────
    ' OUT_RECOMMENDATION must be a workbook-scoped named range pointing to the
    ' IF formula cell on SUMMARY.  Evaluate captures the formula's result text.
    Dim sRecommendation As String
    sRecommendation = CStr(ThisWorkbook.Evaluate("OUT_RECOMMENDATION"))

    ' ── Create the report sheet ───────────────────────────────────────────────
    Dim wsReport As Worksheet  ' Nothing until Add succeeds
    Set wsReport = ThisWorkbook.Worksheets.Add(Before:=ThisWorkbook.Worksheets(1))
    wsReport.Name = sRptName  ' timestamped; name collision is vanishingly unlikely

    ' ── Populate content ──────────────────────────────────────────────────────
    Call BuildReportContent(wsReport, sStampDisplay, _
                            dCost, dBalance, dNIM, dTenor, dRetention, _
                            dMppcT1, dMppcT2, dMppcT3, dVoT, dGpT1T2, _
                            sRecommendation)

    ' ── Page setup: A4 portrait, fit everything to one page ──────────────────
    ' Zoom must be False when FitToPages dimensions are set; setting it after
    ' FitToPages would silently override them.
    With wsReport.PageSetup
        .Zoom               = False
        .PaperSize          = xlPaperA4
        .Orientation        = xlPortrait
        .FitToPagesWide     = 1
        .FitToPagesTall     = 1
        .TopMargin          = Application.InchesToPoints(0.75)
        .BottomMargin       = Application.InchesToPoints(0.75)
        .LeftMargin         = Application.InchesToPoints(0.75)
        .RightMargin        = Application.InchesToPoints(0.75)
        .CenterHorizontally = True
        .PrintGridlines     = False
        .PrintHeadings      = False
    End With

    ' ── Export to PDF ─────────────────────────────────────────────────────────
    Dim sPdfPath As String
    sPdfPath = ThisWorkbook.Path & Application.PathSeparator & sRptName & ".pdf"

    wsReport.ExportAsFixedFormat _
        Type:=xlTypePDF, _
        Filename:=sPdfPath, _
        Quality:=xlQualityStandard, _
        IncludeDocProperties:=False, _
        IgnorePrintAreas:=False, _
        OpenAfterPublish:=False

    ' ── Lock the finished report sheet ───────────────────────────────────────
    ' The report is a read-only snapshot; protect it so users cannot accidentally
    ' edit it.  No cells are unlocked, so everything is locked.
    wsReport.Protect Password:=SHEET_PWD, DrawingObjects:=True, _
                     Contents:=True, Scenarios:=True

    ' ── Normal exit ──────────────────────────────────────────────────────────
    Application.ScreenUpdating = bScreenWasOn
    MsgBox "Report saved:" & vbCrLf & sPdfPath, vbInformation, "FULCRUM"
    Exit Sub

ErrHandler:
    ' Restore application state first — always safe regardless of where we failed.
    Application.ScreenUpdating = bScreenWasOn
    Application.DisplayAlerts  = bAlertsWereOn

    ' Remove any partially-built sheet so the workbook is not left in a broken
    ' state.  wsReport is Nothing only if Worksheets.Add itself failed.
    ' On Error Resume Next prevents a cascade if the delete also fails.
    If Not wsReport Is Nothing Then
        Application.DisplayAlerts = False
        On Error Resume Next
        wsReport.Delete
        On Error GoTo 0
        Application.DisplayAlerts = bAlertsWereOn
    End If

    MsgBox "GenerateCampaignReport failed (Error " & Err.Number & "):" & _
           vbCrLf & Err.Description, vbCritical, "FULCRUM"
End Sub


' =============================================================================
' BuildReportContent  (Private)
' Writes all cell values, formatting, and borders onto the report sheet.
' Separated from GenerateCampaignReport to keep the orchestration sub readable.
'
' All formatting is set by direct property assignment — no .Select/.Activate.
' =============================================================================
Private Sub BuildReportContent(wsR As Worksheet, _
                               sStampDisplay As String, _
                               dCost As Double, _
                               dBalance As Double, _
                               dNIM As Double, _
                               dTenor As Double, _
                               dRetention As Double, _
                               dMppcT1 As Double, _
                               dMppcT2 As Double, _
                               dMppcT3 As Double, _
                               dVoT As Double, _
                               dGpT1T2 As Double, _
                               sRecommendation As String)

    ' ── Sheet-wide defaults ───────────────────────────────────────────────────
    ' Set the base style on the entire sheet first; individual cells override
    ' only the properties that differ, rather than re-setting everything per cell.
    With wsR.Cells.Font
        .Name  = "Calibri"
        .Size  = 11
        .Bold  = False
        .Color = CLR_TEXT
    End With
    wsR.Cells.Interior.ColorIndex = xlNone

    ' Only columns A (labels) and B (values) are used.
    wsR.Columns("A").ColumnWidth = 34
    wsR.Columns("B").ColumnWidth = 20

    ' Spacer rows between sections — set height once here, not per-section.
    wsR.Rows(2).RowHeight  = 6   ' gap: title → assumptions
    wsR.Rows(9).RowHeight  = 8   ' gap: assumptions → metrics
    wsR.Rows(16).RowHeight = 8   ' gap: metrics → recommendation
    wsR.Rows(19).RowHeight = 8   ' gap: recommendation → footer

    ' ── Row 1: Title ──────────────────────────────────────────────────────────
    wsR.Range("A1:B1").Merge
    wsR.Cells(RPT_ROW_TITLE, 1).Value = _
        "FULCRUM Campaign Report — " & sStampDisplay
    With wsR.Cells(RPT_ROW_TITLE, 1)
        .Font.Size  = 14
        .Font.Bold  = True
        .Font.Color = CLR_BRAND
        .RowHeight  = 30
    End With
    ' Medium rule below the title in the same brand blue.
    With wsR.Range("A1:B1").Borders(xlEdgeBottom)
        .LineStyle = xlContinuous
        .Weight    = xlMedium
        .Color     = CLR_BRAND
    End With

    ' ── Assumptions section ───────────────────────────────────────────────────
    Call WriteSectionHeader(wsR, RPT_ROW_ASM_HDR, "ASSUMPTIONS")
    Call WriteDataRow wsR, RPT_ROW_ASM1, "Cost per contact", _
                     ChrW(8364) & Format(dCost, "#,##0.00")
    Call WriteDataRow wsR, RPT_ROW_ASM2, "Average deposit balance", _
                     ChrW(8364) & Format(dBalance, "#,##0")
    Call WriteDataRow wsR, RPT_ROW_ASM3, "Net interest margin", _
                     Format(dNIM, "0.00%")
    Call WriteDataRow wsR, RPT_ROW_ASM4, "Deposit tenor", _
                     Format(dTenor, "0.0") & " yr"
    Call WriteDataRow wsR, RPT_ROW_ASM5, "Retention rate (at maturity)", _
                     Format(dRetention, "0%")

    ' ── Headline metrics section ──────────────────────────────────────────────
    Call WriteSectionHeader(wsR, RPT_ROW_MET_HDR, "HEADLINE METRICS")
    Call WriteDataRow wsR, RPT_ROW_MET1, "MPPC — T1 High", _
                     ChrW(8364) & Format(dMppcT1, "#,##0.00")
    Call WriteDataRow wsR, RPT_ROW_MET2, "MPPC — T2 Medium", _
                     ChrW(8364) & Format(dMppcT2, "#,##0.00")
    Call WriteDataRow wsR, RPT_ROW_MET3, "MPPC — T3 Low", _
                     ChrW(8364) & Format(dMppcT3, "#,##0.00")
    Call WriteDataRow wsR, RPT_ROW_MET4, "Value of Targeting T1+T2", _
                     ChrW(8364) & Format(dVoT, "#,##0")
    Call WriteDataRow wsR, RPT_ROW_MET5, "T1+T2 Gross Profit (1 yr)", _
                     ChrW(8364) & Format(dGpT1T2, "#,##0")

    ' ── Recommendation section ────────────────────────────────────────────────
    Call WriteSectionHeader(wsR, RPT_ROW_REC_HDR, "RECOMMENDATION")

    wsR.Range("A18:B18").Merge
    wsR.Cells(RPT_ROW_REC, 1).Value = sRecommendation
    With wsR.Cells(RPT_ROW_REC, 1)
        .Font.Italic = True
        .WrapText    = True
        .RowHeight   = 42   ' extra height in case recommendation wraps to two lines
    End With

    ' ── Footer ────────────────────────────────────────────────────────────────
    wsR.Range("A20:B20").Merge
    wsR.Cells(RPT_ROW_FOOTER, 1).Value = _
        "Generated by FULCRUM v1.0  |  Assumptions: illustrative  |  " & _
        "Source: UCI Bank Marketing dataset, May 2008 – Nov 2010"
    With wsR.Cells(RPT_ROW_FOOTER, 1)
        .Font.Size  = 9
        .Font.Color = CLR_SUBTLE
        .WrapText   = True
        .RowHeight  = 28
    End With
    ' Hairline rule above the footer to visually close the content area.
    With wsR.Range("A20:B20").Borders(xlEdgeTop)
        .LineStyle = xlContinuous
        .Weight    = xlThin
        .Color     = CLR_SUBTLE
    End With

End Sub


' =============================================================================
' WriteSectionHeader  (Private)
' Renders a dark-blue full-width banner spanning columns A–B.
' lRow : the row number on wsR to write into.
' =============================================================================
Private Sub WriteSectionHeader(wsR As Worksheet, lRow As Long, sLabel As String)
    wsR.Range(wsR.Cells(lRow, 1), wsR.Cells(lRow, 2)).Merge
    wsR.Cells(lRow, 1).Value = sLabel
    With wsR.Cells(lRow, 1)
        .Font.Bold      = True
        .Font.Size      = 9
        .Font.Color     = CLR_WHITE
        .Interior.Color = CLR_BRAND
        .RowHeight      = 18
    End With
End Sub


' =============================================================================
' WriteDataRow  (Private)
' Writes a text label (column A) and a pre-formatted value string (column B).
' Even-numbered rows receive a light grey background for alternating shading;
' odd rows stay white.  The pattern is keyed to the absolute row number so it
' stays visually consistent across both content sections without extra logic.
' =============================================================================
Private Sub WriteDataRow(wsR As Worksheet, lRow As Long, _
                         sLabel As String, sValue As String)
    wsR.Cells(lRow, 1).Value = sLabel
    wsR.Cells(lRow, 2).Value = sValue

    With wsR.Cells(lRow, 2)
        .Font.Bold           = True
        .HorizontalAlignment = xlRight
    End With

    If lRow Mod 2 = 0 Then
        wsR.Rows(lRow).Interior.Color = CLR_GREY
    End If

    wsR.Rows(lRow).RowHeight = 18
End Sub


' =============================================================================
' ResetToPointEstimates  (Public — wired to COVER "Reset to Defaults" button)
'
' Writes the five published point-estimate values from pnl_assumptions.yml
' back to the ASM_ named ranges on the INPUTS sheet.  Useful after a scenario
' run or after the data-table sweep has overwritten the Base assumptions.
'
' The macro unprotects INPUTS, writes, then re-protects with UserInterfaceOnly
' so that other macros in this project can subsequently write to unlocked cells
' without needing to unprotect first (the UI-only flag is lost on workbook close,
' but the ASM_ cells are unlocked so VBA can reach them either way).
' =============================================================================
Public Sub ResetToPointEstimates()

    On Error GoTo ErrHandler

    Dim bScreenWasOn As Boolean
    bScreenWasOn = Application.ScreenUpdating
    Application.ScreenUpdating = False

    Dim wsInputs As Worksheet
    Set wsInputs = ThisWorkbook.Worksheets("INPUTS")

    ' Unprotect INPUTS before writing.  Unprotecting an already-unprotected
    ' sheet with an empty password is a silent no-op, so this is always safe.
    wsInputs.Unprotect Password:=SHEET_PWD

    ' Write via workbook-scoped named ranges rather than hard-coded cell
    ' addresses so this macro survives row insertions on the INPUTS sheet.
    ThisWorkbook.Names("ASM_COST").RefersToRange.Value      = PE_COST
    ThisWorkbook.Names("ASM_BALANCE").RefersToRange.Value   = PE_BALANCE
    ThisWorkbook.Names("ASM_NIM").RefersToRange.Value       = PE_NIM
    ThisWorkbook.Names("ASM_TENOR").RefersToRange.Value     = PE_TENOR
    ThisWorkbook.Names("ASM_RETENTION").RefersToRange.Value = PE_RETENTION

    ' Re-protect INPUTS.  UserInterfaceOnly:=True lets macros write to locked
    ' cells without unprotecting while still blocking user edits on locked cells.
    wsInputs.Protect Password:=SHEET_PWD, UserInterfaceOnly:=True

    Application.ScreenUpdating = bScreenWasOn
    Exit Sub

ErrHandler:
    Application.ScreenUpdating = bScreenWasOn
    ' Re-protect INPUTS regardless of where the error occurred — never leave
    ' the sheet open for accidental manual edits after a partial write.
    On Error Resume Next
    ThisWorkbook.Worksheets("INPUTS").Protect Password:=SHEET_PWD, _
                                               UserInterfaceOnly:=True
    On Error GoTo 0
    MsgBox "ResetToPointEstimates failed (Error " & Err.Number & "):" & _
           vbCrLf & Err.Description, vbCritical, "FULCRUM"
End Sub
