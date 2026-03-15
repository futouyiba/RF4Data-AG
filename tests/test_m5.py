"""
M5 真实环境适配验证测试
=====================
验证：
1. 弹窗文本解析 (OCR)
2. FSM 的 LOGGING 状态流转 (弹窗优先 -> 聊天备份 -> 超时)
"""

import sys; sys.path.insert(0, '.')
import time
import re
from unittest.mock import MagicMock, patch
from src.core.fsm import RodFSM, RodState, FishingOrchestrator
from src.core.vision import VisionSensor, DetectionResult, BiteStatus, TensionZone
from src.utils.ocr import OCREngine
from src.data.db import Database
from src.data.models import Event, Catch

def test_popup_ocr():
    print("\n--- Testing Popup OCR Extraction ---")
    ocr = OCREngine()
    
    # 模拟真实弹窗文本
    popup_text = """
    Common Roach
    591 g
    29 cm
    [Valuable]
    [Keep] [Release]
    """
    
    result = ocr.extract_catch_from_popup(popup_text)
    print(f"Input:\n{popup_text}")
    print(f"Result: {result}")
    
    assert result is not None
    assert result['fish_name'] == "Common Roach"
    assert abs(result['weight_kg'] - 0.591) < 0.001
    print("✅ Normal popup parsed successfully")
    
    # 测试 kg 单位
    popup_kg = "Pike\n1.5 kg\nKeep"
    res_kg = ocr.extract_catch_from_popup(popup_kg)
    assert res_kg['weight_kg'] == 1.5
    print("✅ KG unit parsed successfully")

def test_new_chat_format():
    print("\n--- Testing New Chat Format OCR ---")
    ocr = OCREngine()
    
    line = "futouyiba: Gibel Carp, 1.695 kg"
    result = ocr.extract_catch(line)
    print(f"Line: {line} -> {result}")
    assert result['fish_name'] == "Gibel Carp"
    assert result['weight_kg'] == 1.695
    
    line2 = "fisher: Roach, 500 g"
    result2 = ocr.extract_catch(line2)
    print(f"Line: {line2} -> {result2}")
    assert result2['fish_name'] == "Roach"
    assert result2['weight_kg'] == 0.5
    print("✅ New chat formats parsed successfully")

def test_fsm_logging_flow():
    print("\n--- Testing FSM LOGGING Flow ---")
    
    # Setup Mocks
    mock_driver = MagicMock()
    mock_vision = MagicMock()
    mock_capture = MagicMock()
    mock_capture.save_evidence.return_value = "mock_evidence.png"
    
    from src.data.models import Session
    db = Database(':memory:')
    db.init_schema()
    sid = db.create_session(Session())
    
    fsm = RodFSM(1, sid, mock_driver, mock_vision, mock_capture, db)
    
    # 1. 模拟 Retrieving -> Pop-up Catch
    print("Test Case 1: Pop-up Catch")
    fsm.state = RodState.RETRIEVING
    fsm._retrieve_start = time.time() - 10
    
    # Vision: Tension GONE
    mock_vision.detect_tension.return_value = DetectionResult(TensionZone.GONE, 1.0)
    # Update -> Should go to LOGGING
    fsm.update(frame=None)
    assert fsm.state == RodState.LOGGING
    print(f"State transition: RETRIEVING -> {fsm.state}")
    
    # In Logging: Detect Popup
    mock_vision.detect_catch_popup.return_value = DetectionResult(
        {"fish_name": "TestFish", "weight_kg": 1.0}, 0.9
    )
    fsm.update(frame=None)
    
    assert fsm.state == RodState.IDLE
    assert mock_driver.press.call_args[0][0] == 'space'
    print("Locked catch via Popup, pressed SPACE, back to IDLE")
    
    # Verify DB
    catch = db.conn.execute("SELECT * FROM catches ORDER BY catch_id DESC LIMIT 1").fetchone()
    assert catch['fish_name_raw'] == 'TestFish'
    assert catch['outcome'] == 'CATCH'
    
    # 2. 模拟 Retreiving -> Chat Catch (Popup missed)
    print("\nTest Case 2: Chat Catch (Backup)")
    fsm.state = RodState.LOGGING
    fsm._state_enter_time = time.time() # Just entered
    
    # Vision: No popup, but chat has it
    mock_vision.detect_catch_popup.return_value = DetectionResult(None, 0.0)
    mock_vision.detect_catch_from_chat.return_value = DetectionResult(
        {"fish_name": "ChatFish", "weight_kg": 2.0}, 0.8
    )
    
    fsm.update(frame=None)
    assert fsm.state == RodState.IDLE
    print("Locked catch via Chat, back to IDLE")
    
    # 3. 模拟 Timeout (Empty)
    print("\nTest Case 3: Timeout (Empty Retrieve)")
    fsm.state = RodState.LOGGING
    fsm._state_enter_time = time.time() - 9.0 # > 8s timeout
    
    mock_vision.detect_catch_popup.return_value = DetectionResult(None, 0.0)
    mock_vision.detect_catch_from_chat.return_value = DetectionResult(None, 0.0)
    
    fsm.update(frame=None)
    assert fsm.state == RodState.IDLE
    print("Timeout reached, back to IDLE (Empty)")

    db.close()

if __name__ == "__main__":
    try:
        test_popup_ocr()
        test_new_chat_format()
        test_fsm_logging_flow()
        print("\n✅ All M5 tests passed!")
    except AssertionError as e:
        print(f"\n❌ Assertion Failed: {e}")
        import traceback; traceback.print_exc()
        exit(1)
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback; traceback.print_exc()
        exit(1)

