bl_info = {
    "name": "LRC to 3D Text (Final Stable)",
    "author": "far-chen",
    "version": (3, 10),
    "blender": (5, 0, 0),
    "location": "3D View > Sidebar > LRC歌词模型",
    "description": "稳定版LRC歌词转换插件，导入后自动刷新列表。",
    "category": "Import-Export",
}

import bpy
import re
import os
import random
from math import radians
from bpy.props import (StringProperty, FloatProperty, IntProperty,
                       BoolProperty, EnumProperty)
from bpy.types import Operator, Panel, PropertyGroup

# ---------- 材质缓存 ----------
_material_cache = {}

def get_or_create_material(color, name_suffix):
    global _material_cache
    key = f"{color[0]:.5f}_{color[1]:.5f}_{color[2]:.5f}_{color[3]:.5f}"
    if key in _material_cache:
        return _material_cache[key]
    mat_name = f"LyricMat_{name_suffix}_{int(color[0]*255)}_{int(color[1]*255)}_{int(color[2]*255)}"
    if mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
    else:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get('Principled BSDF')
        if bsdf is None:
            bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
            output = nodes.get('Material Output')
            if output is None:
                output = nodes.new(type='ShaderNodeOutputMaterial')
            mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
        bsdf.inputs['Base Color'].default_value = color
        bsdf.inputs['Alpha'].default_value = color[3]
        mat.blend_method = 'BLEND'
        mat["bsdf_node"] = bsdf
    _material_cache[key] = mat
    return mat

def clear_material_cache():
    global _material_cache
    _material_cache.clear()

# ---------- LRC 解析 ----------
def parse_lrc_file(filepath):
    lyrics = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pattern = r'\[(\d+):(\d+(?:\.\d+)?)\]'
            matches = re.findall(pattern, line)
            if not matches:
                continue
            text = re.sub(pattern, '', line).strip()
            if not text:
                continue
            minute, sec = matches[0]
            seconds = int(minute) * 60 + float(sec)
            lyrics.append((seconds, text))
    lyrics.sort(key=lambda x: x[0])
    return lyrics

# ---------- 创建文本曲线 ----------
def create_text_curve(text, location, font_path, size=1.0, name_prefix="Lyric",
                      center_align=True, resolution_u=3, extrude=0.02, bevel=0.005):
    curve = bpy.data.curves.new(name=name_prefix + "_curve", type='FONT')
    obj = bpy.data.objects.new(name_prefix, curve)
    bpy.context.collection.objects.link(obj)

    curve.body = text
    if font_path and os.path.exists(font_path):
        font = bpy.data.fonts.load(font_path)
        curve.font = font
    curve.size = size
    curve.extrude = extrude
    curve.bevel_depth = bevel
    curve.resolution_u = max(1, min(10, resolution_u))
    curve.bevel_resolution = 0
    if center_align:
        curve.align_x = 'CENTER'
        curve.align_y = 'CENTER'
    obj.location = location
    return obj

# ---------- 动画特效 ----------
def apply_effects(obj, start_frame, end_frame, effect_in, effect_out, effect_duration, frame_rate):
    if effect_in == 'none' and effect_out == 'none':
        return

    duration_frames = int(effect_duration * frame_rate)
    in_start = start_frame
    in_end = min(start_frame + duration_frames, end_frame)
    out_start = max(end_frame - duration_frames, start_frame)
    out_end = end_frame

    if not obj.animation_data:
        obj.animation_data_create()
    if not obj.animation_data.action:
        action = bpy.data.actions.new(f"{obj.name}_action")
        obj.animation_data.action = action

    loc_start = obj.location.copy()
    scale_start = obj.scale.copy()
    rot_start = obj.rotation_euler.copy()

    def insert_keyframe(frame, location=None, scale=None, rotation=None):
        if location is not None:
            obj.location = location
            obj.keyframe_insert(data_path="location", frame=frame)
        if scale is not None:
            obj.scale = scale
            obj.keyframe_insert(data_path="scale", frame=frame)
        if rotation is not None:
            obj.rotation_euler = rotation
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)

    if effect_in != 'none':
        if effect_in == 'fade':
            set_material_alpha_fast(obj, 0.0, in_start)
            set_material_alpha_fast(obj, 1.0, in_end)
        elif effect_in == 'pop':
            insert_keyframe(in_start, scale=(0, 0, 0))
            insert_keyframe(in_end, scale=scale_start)
        elif effect_in == 'rotate':
            rot_in = (radians(-90), 0, 0)
            insert_keyframe(in_start, rotation=rot_in)
            insert_keyframe(in_end, rotation=rot_start)
        elif effect_in == 'slide':
            loc_in = loc_start + (-3, 0, 0)
            insert_keyframe(in_start, location=loc_in)
            insert_keyframe(in_end, location=loc_start)

    if effect_out != 'none':
        if effect_out == 'fade':
            set_material_alpha_fast(obj, 1.0, out_start)
            set_material_alpha_fast(obj, 0.0, out_end)
        elif effect_out == 'pop':
            insert_keyframe(out_start, scale=scale_start)
            insert_keyframe(out_end, scale=(0, 0, 0))
        elif effect_out == 'rotate':
            rot_out = (radians(90), 0, 0)
            insert_keyframe(out_start, rotation=rot_start)
            insert_keyframe(out_end, rotation=rot_out)
        elif effect_out == 'slide':
            loc_out = loc_start + (3, 0, 0)
            insert_keyframe(out_start, location=loc_start)
            insert_keyframe(out_end, location=loc_out)

def set_material_alpha_fast(obj, alpha, frame):
    if not obj.data.materials:
        return
    mat = obj.data.materials[0]
    if not mat.node_tree:
        return
    bsdf = mat.get("bsdf_node")
    if bsdf is None:
        for node in mat.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                bsdf = node
                mat["bsdf_node"] = bsdf
                break
    if bsdf:
        bsdf.inputs['Alpha'].default_value = alpha
        bsdf.inputs['Alpha'].keyframe_insert(data_path="default_value", frame=frame)
        mat.blend_method = 'BLEND'

def set_visibility_keyframes_optimized(obj, start_frame, end_frame):
    if start_frame > 0:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=start_frame - 1)
        obj.keyframe_insert(data_path="hide_render", frame=start_frame - 1)
    obj.hide_viewport = False
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_viewport", frame=start_frame)
    obj.keyframe_insert(data_path="hide_render", frame=start_frame)
    obj.hide_viewport = True
    obj.hide_render = True
    obj.keyframe_insert(data_path="hide_viewport", frame=end_frame)
    obj.keyframe_insert(data_path="hide_render", frame=end_frame)

# ---------- 清除所有歌词 ----------
def clear_lyrics_group():
    group = bpy.data.objects.get("Lyrics_Group")
    if group:
        for child in group.children[:]:
            bpy.data.objects.remove(child, do_unlink=True)
        bpy.data.objects.remove(group, do_unlink=True)
    else:
        for obj in list(bpy.data.objects):
            if obj.get("lrc_start") is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
    clear_material_cache()

# ---------- 核心生成函数 ----------
def generate_lyrics_from_file(context, filepath):
    scene = context.scene
    props = scene.lrc_props

    if not filepath or not os.path.exists(filepath):
        return False, "文件不存在或未选择"

    try:
        lyrics = parse_lrc_file(filepath)
    except Exception as e:
        return False, f"解析失败: {e}"

    if not lyrics:
        return False, "没有有效的歌词行"

    if props.clear_old:
        clear_lyrics_group()

    group = bpy.data.objects.new("Lyrics_Group", None)
    bpy.context.collection.objects.link(group)

    frame_rate = scene.render.fps
    frame_offset = props.start_frame_offset

    time_pairs = []
    for i, (start_sec, text) in enumerate(lyrics):
        end_sec = lyrics[i+1][0] if i+1 < len(lyrics) else start_sec + 4.0
        time_pairs.append((start_sec, end_sec, text))

    if props.high_performance_mode:
        effect_in = 'fade'
        effect_out = 'fade'
    else:
        effect_in = props.effect_in
        effect_out = props.effect_out

    if props.use_random_color:
        colors = [(random.uniform(0.5,1.0), random.uniform(0.3,1.0), random.uniform(0.3,1.0), 1.0)
                  for _ in time_pairs]
        use_shared_mat = False
    else:
        uniform = (props.text_color_r, props.text_color_g, props.text_color_b, 1.0)
        colors = [uniform] * len(time_pairs)
        use_shared_mat = True

    res_u = props.geometry_simplify
    extrude = props.extrude_depth
    bevel = props.bevel_depth

    item_list = []
    try:
        if props.vertical_layout:
            y_offset = 0.0
            for idx, (start_sec, end_sec, text) in enumerate(time_pairs):
                loc = (props.start_x, props.start_y - y_offset, props.start_z)
                obj = create_text_curve(
                    text=text, location=loc, font_path=props.font_path,
                    size=props.font_size, name_prefix=f"Lyric_{int(start_sec*100):06d}",
                    center_align=props.center_align, resolution_u=res_u,
                    extrude=extrude, bevel=bevel
                )
                obj.parent = group
                obj["lrc_start"] = start_sec
                obj["lrc_end"] = end_sec
                obj["lrc_text"] = text
                item_list.append((obj, start_sec, end_sec, colors[idx]))
                y_offset += props.line_spacing
                if (idx+1) % 20 == 0:
                    bpy.context.view_layer.update()
        else:
            loc = (props.start_x, props.start_y, props.start_z)
            for idx, (start_sec, end_sec, text) in enumerate(time_pairs):
                obj = create_text_curve(
                    text=text, location=loc, font_path=props.font_path,
                    size=props.font_size, name_prefix=f"Lyric_{int(start_sec*100):06d}",
                    center_align=props.center_align, resolution_u=res_u,
                    extrude=extrude, bevel=bevel
                )
                obj.parent = group
                obj["lrc_start"] = start_sec
                obj["lrc_end"] = end_sec
                obj["lrc_text"] = text
                item_list.append((obj, start_sec, end_sec, colors[idx]))
                if (idx+1) % 20 == 0:
                    bpy.context.view_layer.update()
    except MemoryError:
        for obj, _, _, _ in item_list:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.objects.remove(group, do_unlink=True)
        return False, "内存不足，请减少歌词数量或降低简化度"

    obj_material = {}
    if use_shared_mat:
        shared_mat = get_or_create_material(colors[0], "Shared")
        for obj, _, _, _ in item_list:
            obj_material[obj] = shared_mat
    else:
        color_mat = {}
        for obj, _, _, color in item_list:
            key = f"{color[0]:.3f}_{color[1]:.3f}_{color[2]:.3f}_{color[3]:.3f}"
            if key not in color_mat:
                color_mat[key] = get_or_create_material(color, f"Color_{key}")
            obj_material[obj] = color_mat[key]

    success_objs = []
    total = len(item_list)
    for idx, (obj, start_sec, end_sec, color) in enumerate(item_list):
        start_frame = int(start_sec * frame_rate) + frame_offset
        end_frame = int(end_sec * frame_rate) + frame_offset
        try:
            mat = obj_material[obj]
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)

            set_visibility_keyframes_optimized(obj, start_frame, end_frame)
            if effect_in != 'none' or effect_out != 'none':
                apply_effects(obj, start_frame, end_frame,
                              effect_in, effect_out,
                              props.effect_duration, frame_rate)
            success_objs.append(obj)
        except Exception as e:
            context.report({'WARNING'}, f"物体 {obj.name} 分配失败: {e}")

        if (idx+1) % 20 == 0:
            bpy.context.view_layer.update()

    props.generated_objects.clear()
    for obj in success_objs:
        item = props.generated_objects.add()
        item.name = obj.name
    props.group_name = group.name
    props.last_import_path = filepath

    return True, f"成功生成 {len(success_objs)} / {total} 句歌词"

# ---------- 保留物体的动画刷新 ----------
def refresh_animation_preserve_objects(context):
    scene = context.scene
    props = scene.lrc_props
    frame_rate = scene.render.fps
    frame_offset = props.start_frame_offset

    items = props.lyrics_edit
    if not items:
        context.report({'WARNING'}, "无歌词数据，请先同步列表")
        return False, "无歌词数据"

    if props.high_performance_mode:
        effect_in = 'fade'
        effect_out = 'fade'
    else:
        effect_in = props.effect_in
        effect_out = props.effect_out

    success_count = 0
    for idx, item in enumerate(items):
        obj_name = item.obj_name
        if obj_name not in bpy.data.objects:
            continue
        obj = bpy.data.objects[obj_name]
        start_sec = item.start_sec
        end_sec = item.end_sec
        new_text = item.text_line

        if obj.data.body != new_text:
            obj.data.body = new_text
            obj["lrc_text"] = new_text

        if obj.animation_data:
            obj.animation_data_clear()
        start_frame = int(start_sec * frame_rate) + frame_offset
        end_frame = int(end_sec * frame_rate) + frame_offset
        set_visibility_keyframes_optimized(obj, start_frame, end_frame)
        if effect_in != 'none' or effect_out != 'none':
            apply_effects(obj, start_frame, end_frame,
                          effect_in, effect_out,
                          props.effect_duration, frame_rate)
        obj["lrc_start"] = start_sec
        obj["lrc_end"] = end_sec
        success_count += 1

        if (idx+1) % 20 == 0:
            bpy.context.view_layer.update()

    return True, f"已刷新 {success_count} 个物体的动画"

# ---------- 诊断：临时禁用挤出/倒角 ----------
class LRC_OT_diagnose_extrude(Operator):
    bl_idname = "lrc.diagnose_extrude"
    bl_label = "诊断：临时禁用挤出/倒角"
    bl_description = "将所有歌词物体的挤出和倒角深度设为0（临时平面化），帮助定位突起问题。刷新动画或重新导入即可恢复。"

    def execute(self, context):
        objs = [obj for obj in bpy.data.objects if obj.get("lrc_start") is not None]
        if not objs:
            self.report({'WARNING'}, "没有找到任何歌词物体")
            return {'CANCELLED'}
        for obj in objs:
            if obj.data:
                obj.data.extrude = 0.0
                obj.data.bevel_depth = 0.0
        self.report({'INFO'}, f"已临时禁用 {len(objs)} 个歌词物体的挤出和倒角。如需恢复，请使用「刷新动画」或「重新导入」。")
        return {'FINISHED'}

# ---------- 操作符 ----------
class LRC_OT_import_and_generate(Operator):
    bl_idname = "lrc.import_and_generate"
    bl_label = "导入 LRC 并生成模型"
    bl_description = "选择LRC文件，创建低面数3D歌词"

    filepath: StringProperty(subtype='FILE_PATH')

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "请选择文件")
            return {'CANCELLED'}
        success, msg = generate_lyrics_from_file(context, self.filepath)
        if success:
            self.report({'INFO'}, msg)
            # 自动刷新歌词编辑列表
            bpy.ops.lrc.sync_edit_list()
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class LRC_OT_global_refresh(Operator):
    bl_idname = "lrc.global_refresh"
    bl_label = "重新导入（清除并重建）"
    bl_description = "使用上次导入的文件路径和当前设置，清除所有模型后重新生成"

    def execute(self, context):
        props = context.scene.lrc_props
        if not props.last_import_path or not os.path.exists(props.last_import_path):
            self.report({'WARNING'}, "没有有效的上次导入文件，请先导入LRC文件")
            return {'CANCELLED'}
        success, msg = generate_lyrics_from_file(context, props.last_import_path)
        if success:
            self.report({'INFO'}, msg)
            bpy.ops.lrc.sync_edit_list()
        else:
            self.report({'ERROR'}, msg)
        return {'FINISHED'}

class LRC_OT_refresh_animation(Operator):
    bl_idname = "lrc.refresh_animation"
    bl_label = "刷新动画（保留物体）"
    bl_description = "根据当前编辑列表更新现有歌词物体的动画和文本，不删除物体"

    def execute(self, context):
        success, msg = refresh_animation_preserve_objects(context)
        if success:
            self.report({'INFO'}, msg)
        else:
            self.report({'WARNING'}, msg)
        return {'FINISHED'}

class LRC_OT_update_keyframes(Operator):
    bl_idname = "lrc.update_keyframes"
    bl_label = "更新关键帧"
    bl_description = "根据当前编辑列表重新生成关键帧（与刷新动画功能相同）"

    def execute(self, context):
        success, msg = refresh_animation_preserve_objects(context)
        if success:
            self.report({'INFO'}, msg)
        else:
            self.report({'WARNING'}, msg)
        return {'FINISHED'}

class LRC_OT_temporary_show_all(Operator):
    bl_idname = "lrc.temporary_show_all"
    bl_label = "临时显示所有歌词"
    def execute(self, context):
        objs = [obj for obj in bpy.data.objects if obj.get("lrc_start") is not None]
        if not objs:
            self.report({'WARNING'}, "没有找到任何歌词物体")
            return {'CANCELLED'}
        for obj in objs:
            if obj.animation_data and obj.animation_data.action:
                action = obj.animation_data.action
                fcurves_to_remove = [fc for fc in action.fcurves if fc.data_path in {"hide_viewport","hide_render"}]
                for fc in fcurves_to_remove:
                    action.fcurves.remove(fc)
            obj.hide_viewport = False
            obj.hide_render = False
        self.report({'INFO'}, f"已临时显示 {len(objs)} 个歌词物体")
        return {'FINISHED'}

class LRC_OT_restore_animation(Operator):
    bl_idname = "lrc.restore_animation"
    bl_label = "恢复动画"
    def execute(self, context):
        bpy.ops.lrc.update_keyframes()
        self.report({'INFO'}, "动画已恢复")
        return {'FINISHED'}

class LRC_OT_clear_models(Operator):
    bl_idname = "lrc.clear_models"
    bl_label = "清除所有模型"
    def execute(self, context):
        props = context.scene.lrc_props
        if props.group_name and props.group_name in bpy.data.objects:
            group = bpy.data.objects[props.group_name]
            for child in group.children[:]:
                bpy.data.objects.remove(child, do_unlink=True)
            bpy.data.objects.remove(group, do_unlink=True)
        else:
            for obj in list(bpy.data.objects):
                if obj.get("lrc_start") is not None:
                    bpy.data.objects.remove(obj, do_unlink=True)
        props.generated_objects.clear()
        props.lyrics_edit.clear()
        props.group_name = ""
        clear_material_cache()
        self.report({'INFO'}, "已清除所有模型")
        return {'FINISHED'}

class LRC_OT_sync_edit_list(Operator):
    bl_idname = "lrc.sync_edit_list"
    bl_label = "刷新列表"
    def execute(self, context):
        props = context.scene.lrc_props
        props.lyrics_edit.clear()
        objs = [obj for obj in bpy.data.objects if obj.get("lrc_start") is not None]
        objs.sort(key=lambda o: o["lrc_start"])
        for obj in objs:
            item = props.lyrics_edit.add()
            item.obj_name = obj.name
            item.start_sec = obj["lrc_start"]
            item.end_sec = obj.get("lrc_end", obj["lrc_start"]+4.0)
            item.text_line = obj.get("lrc_text", obj.data.body)
        self.report({'INFO'}, f"同步了 {len(objs)} 行歌词")
        return {'FINISHED'}

# ---------- 属性定义 ----------
class LRC_LyricItem(PropertyGroup):
    obj_name: StringProperty()
    start_sec: FloatProperty(default=0.0)
    end_sec: FloatProperty(default=4.0)
    text_line: StringProperty(default="")

class LRC_ObjectItem(PropertyGroup):
    name: StringProperty()

class LRC_Properties(PropertyGroup):
    last_import_path: StringProperty(default="")
    font_path: StringProperty(name="字体文件", subtype='FILE_PATH')
    start_frame_offset: IntProperty(name="开始帧偏移", default=0, min=0)
    extrude_depth: FloatProperty(name="挤出深度", default=0.02, min=0, max=0.1, step=0.001, precision=3)
    bevel_depth: FloatProperty(name="倒角深度", default=0.005, min=0, max=0.05, step=0.001, precision=3)
    font_size: FloatProperty(name="基础大小", default=1.0, min=0.1)
    line_spacing: FloatProperty(name="行间距", default=1.5, min=0.5)
    start_x: FloatProperty(name="起始X", default=0.0)
    start_y: FloatProperty(name="起始Y", default=0.0)
    start_z: FloatProperty(name="起始Z", default=0.0)
    text_color_r: FloatProperty(name="颜色R", default=1.0, min=0, max=1)
    text_color_g: FloatProperty(name="颜色G", default=1.0, min=0, max=1)
    text_color_b: FloatProperty(name="颜色B", default=1.0, min=0, max=1)
    use_random_color: BoolProperty(name="随机颜色", default=False)
    center_align: BoolProperty(name="文本居中", default=True)
    vertical_layout: BoolProperty(name="垂直排列", default=False)
    high_performance_mode: BoolProperty(name="高性能模式", default=False)
    geometry_simplify: IntProperty(name="模型简化度", default=3, min=1, max=10)
    effect_in: EnumProperty(name="入场特效", items=[('none','无',''),('fade','淡入',''),('pop','弹入',''),('rotate','旋转入',''),('slide','滑入','')], default='fade')
    effect_out: EnumProperty(name="离场特效", items=[('none','无',''),('fade','淡出',''),('pop','弹出',''),('rotate','旋转出',''),('slide','滑出','')], default='fade')
    effect_duration: FloatProperty(name="特效时长(秒)", default=0.5, min=0.1, max=2.0)
    clear_old: BoolProperty(name="生成前清除旧模型", default=True)
    generated_objects: bpy.props.CollectionProperty(type=LRC_ObjectItem)
    lyrics_edit: bpy.props.CollectionProperty(type=LRC_LyricItem)
    group_name: StringProperty(default="")

# ---------- UI 面板 ----------
class LRC_PT_main_panel(Panel):
    bl_label = "LRC歌词模型"
    bl_idname = "LRC_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LRC歌词模型"
    def draw(self, context):
        pass

class LRC_PT_import_clear(Panel):
    bl_label = "📁 导入与清除"
    bl_idname = "LRC_PT_import_clear"
    bl_parent_id = "LRC_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    def draw(self, context):
        layout = self.layout
        props = context.scene.lrc_props
        row = layout.row(align=True)
        row.operator("lrc.import_and_generate", icon='FILE_FOLDER')
        row.operator("lrc.clear_models", icon='X')
        layout.separator()
        layout.prop(props, "start_frame_offset")
        layout.prop(props, "font_path")

class LRC_PT_model_effects(Panel):
    bl_label = "⚙️ 模型与特效"
    bl_idname = "LRC_PT_model_effects"
    bl_parent_id = "LRC_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout
        props = context.scene.lrc_props
        row = layout.row(align=True)
        row.operator("lrc.global_refresh", icon='FILE_REFRESH', text="重新导入")
        row.operator("lrc.refresh_animation", icon='TIME', text="刷新动画")
        layout.separator()
        layout.prop(props, "font_size")
        layout.prop(props, "line_spacing")
        layout.prop(props, "clear_old")
        layout.prop(props, "vertical_layout")
        layout.prop(props, "center_align")
        layout.prop(props, "high_performance_mode")
        layout.prop(props, "geometry_simplify", slider=True)
        layout.separator()
        layout.label(text="立体感调节")
        layout.prop(props, "extrude_depth", slider=True)
        layout.prop(props, "bevel_depth", slider=True)
        layout.separator()
        layout.operator("lrc.diagnose_extrude", icon='INFO')
        if props.high_performance_mode:
            layout.label(text="特效: 强制淡入/淡出", icon='INFO')
        else:
            layout.label(text="特效设置")
            row = layout.row()
            row.prop(props, "effect_in")
            row.prop(props, "effect_out")
            layout.prop(props, "effect_duration")

class LRC_PT_position_color(Panel):
    bl_label = "🎨 位置与颜色"
    bl_idname = "LRC_PT_position_color"
    bl_parent_id = "LRC_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout
        props = context.scene.lrc_props
        row = layout.row(align=True)
        row.prop(props, "start_x")
        row.prop(props, "start_y")
        row.prop(props, "start_z")
        layout.separator()
        row = layout.row(align=True)
        row.prop(props, "text_color_r")
        row.prop(props, "text_color_g")
        row.prop(props, "text_color_b")
        layout.prop(props, "use_random_color")

class LRC_PT_lyrics_edit(Panel):
    bl_label = "✏️ 歌词编辑"
    bl_idname = "LRC_PT_lyrics_edit"
    bl_parent_id = "LRC_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        layout = self.layout
        props = context.scene.lrc_props
        row = layout.row(align=True)
        row.operator("lrc.temporary_show_all", icon='HIDE_OFF')
        row.operator("lrc.restore_animation", icon='TIME')
        layout.separator()
        if props.lyrics_edit:
            col = layout.column(align=True)
            for idx, item in enumerate(props.lyrics_edit):
                row = col.row(align=True)
                row.prop(item, "start_sec", text="开始")
                row.prop(item, "end_sec", text="结束")
                row = col.row(align=True)
                row.prop(item, "text_line", text="")
                if idx < len(props.lyrics_edit)-1:
                    col.separator()
            layout.operator("lrc.update_keyframes", icon='TIME')
        else:
            layout.label(text="暂无歌词，请先导入或刷新列表")

# ---------- 注册 ----------
classes = [
    LRC_LyricItem, LRC_ObjectItem, LRC_Properties,
    LRC_OT_import_and_generate, LRC_OT_global_refresh, LRC_OT_refresh_animation,
    LRC_OT_update_keyframes, LRC_OT_clear_models, LRC_OT_sync_edit_list,
    LRC_OT_temporary_show_all, LRC_OT_restore_animation,
    LRC_OT_diagnose_extrude,
    LRC_PT_main_panel, LRC_PT_import_clear, LRC_PT_model_effects,
    LRC_PT_position_color, LRC_PT_lyrics_edit,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lrc_props = bpy.props.PointerProperty(type=LRC_Properties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lrc_props
    clear_material_cache()

if __name__ == "__main__":
    register()