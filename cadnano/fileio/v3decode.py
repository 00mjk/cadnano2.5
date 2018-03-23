# -*- coding: utf-8 -*-
from typing import Tuple

from cadnano.fileio.lattice import HoneycombDnaPart, SquareDnaPart
from cadnano.part.nucleicacidpart import DEFAULT_RADIUS
from cadnano.part.refresholigoscmd import RefreshOligosCommand
from cadnano.proxies.cnenum import GridType, PointType, OrthoViewType
from cadnano.objectinstance import ObjectInstance

def decode(document, obj, emit_signals=False):
    """ Decode a a deserialized Document dictionary

    Args:
        document (Document):
        obj (dict): deserialized file object
    """
    obj.get('name')
    meta = obj.get('meta', {})

    # TODO[NF]:  Use a constant here
    ortho_view_type = meta.get('ortho_view_type')

    # This assumes that the lattice without a specified grid type is a honeycomb lattice
    grid_type = meta.get('grid_type', GridType.HONEYCOMB)

    for part_dict in obj['parts']:
        decodePart(document, part_dict, grid_type=grid_type,
                   emit_signals=emit_signals)

        if ortho_view_type is None:
            ortho_view_type = determineOrthoViewType(document, part_dict, grid_type)

    modifications = obj['modifications']

    for mod_id, item in modifications.items():
        document.createMod(item['props'], mod_id)
        ext_locations = item['ext_locations']
        for key in ext_locations:
            part, strand, idx = document.getModStrandIdx(key)
            part.addModStrandInstance(strand, idx, mod_id)

    # This can be None if the encode did encode with a GUI
    if ortho_view_type and ortho_view_type != 'None':
        document.setOrthoViewType(ortho_view_type=ortho_view_type)
# end def


def determineOrthoViewType(document, part_dict, grid_type):
    THRESHOLD = 0.0005
    vh_id_list = part_dict.get('vh_list')
    origins = part_dict.get('origins')

    for vh_id, size in vh_id_list:
        vh_x, vh_y = origins[vh_id]

        if grid_type is GridType.HONEYCOMB:
            distance, point = HoneycombDnaPart.distanceFromClosestLatticeCoord(vh_x, vh_y, DEFAULT_RADIUS)
            if distance > THRESHOLD:
                return OrthoViewType.GRID
        elif grid_type is GridType.SQUARE:
            if SquareDnaPart.distanceFromClosestLatticeCoord(vh_x, vh_y, DEFAULT_RADIUS)[0] > THRESHOLD:
                return OrthoViewType.GRID
    return OrthoViewType.SLICE
# end def


def decodePart(document, part_dict, grid_type, emit_signals=False):
    """ Decode a a deserialized Part dictionary

    Args:
        document (Document):
        part_dict (dict): deserialized dictionary describing the Part
    """
    part = document.createNucleicAcidPart(use_undostack=False, grid_type=grid_type)
    part.setActive(True)

    vh_id_list = part_dict.get('vh_list')
    vh_props = part_dict.get('virtual_helices')
    origins = part_dict.get('origins')
    keys = list(vh_props.keys())

    if part_dict.get('point_type') == PointType.ARBITRARY:
        # TODO add code to deserialize parts
        pass
    else:
        for id_num, size in vh_id_list:
            x, y = origins[id_num]
            z = vh_props['z'][id_num]
            vh_props['eulerZ'][id_num] = 0.5*(360./10.5)
            vals = [vh_props[k][id_num] for k in keys]
            part.createVirtualHelix(x, y, z, size,
                                    id_num=id_num,
                                    properties=(keys, vals),
                                    safe=False,
                                    use_undostack=False)
        # end for
        # zoom to fit
        if emit_signals:
            part.partZDimensionsChangedSignal.emit(part, *part.zBoundsIds(), True)

    strands = part_dict['strands']
    strand_index_list = strands['indices']
    color_list = strands['properties']
    for i in range(len(vh_id_list)):
        id_num = vh_id_list[i][0]
        idx_set = strand_index_list[i]
        if idx_set is not None:
            fwd_strand_set, rev_strand_set = part.getStrandSets(id_num)
            fwd_idxs, rev_idxs = idx_set
            fwd_colors, rev_colors = color_list[i]
            for idxs, color in zip(fwd_idxs, fwd_colors):
                low_idx, high_idx = idxs
                fwd_strand_set.createDeserializedStrand(low_idx, high_idx, color,
                                                        use_undostack=False)
            for idxs, color in zip(rev_idxs, rev_colors):
                low_idx, high_idx = idxs
                rev_strand_set.createDeserializedStrand(low_idx, high_idx, color,
                                                        use_undostack=False)
            part.refreshSegments(id_num)   # update segments
    # end def

    xovers = part_dict['xovers']
    for from_id, from_is_fwd, from_idx, to_id, to_is_fwd, to_idx in xovers:
        from_strand = part.getStrand(from_is_fwd, from_id, from_idx)
        to_strand = part.getStrand(to_is_fwd, to_id, to_idx)
        part.createXover(from_strand, from_idx,
                         to_strand, to_idx,
                         update_oligo=False,
                         use_undostack=False)

    RefreshOligosCommand(part).redo()
    for oligo in part_dict['oligos']:
        id_num = oligo['id_num']
        idx = oligo['idx5p']
        is_fwd = oligo['is_5p_fwd']
        color = oligo['color']
        sequence = oligo['sequence']
        strand5p = part.getStrand(is_fwd, id_num, idx)
        this_oligo = strand5p.oligo()
        # this_oligo.applyColor(color, use_undostack=False)
        if sequence is not None:
            this_oligo.applySequence(sequence, use_undostack=False)

    # INSERTIONS, SKIPS
    for id_num, idx, length in part_dict['insertions']:
        fwd_strand = part.getStrand(True, id_num, idx)
        rev_strand = part.getStrand(False, id_num, idx)
        if fwd_strand:
            fwd_strand.addInsertion(idx, length, use_undostack=False)
        elif rev_strand:
            rev_strand.addInsertion(idx, length, use_undostack=False)
        else:
            ins = 'Insertion' if length > 0 else 'Skip'
            print("Cannot find strand for {} at {}[{}]".format(ins, id_num, idx))

    # TODO fix this to set position
    # instance_props = part_dict['instance_properties']    # list

    vh_order = part_dict['virtual_helix_order']
    if vh_order:
        # print("import order", vh_order)
        part.setImportedVHelixOrder(vh_order)

    # Restore additional Part properties
    for key in ['name',
                'color',
                'crossover_span_angle',
                'max_vhelix_length'
                ]:
        value = part_dict[key]
        part.setProperty(key, value, use_undostack=False)
        part.partPropertyChangedSignal.emit(part, key, value)
# end def


def importToPart(   part_instance : ObjectInstance,
                    copy_dict: dict,
                    offset: Tuple[float, float] = None,
                    use_undostack: bool = True):
    """Use this to duplicate virtual_helices within a ``Part``.  duplicate
    ``id_num``s will start numbering ``part.getMaxIdNum() + 1`` rather than the
    lowest available ``id_num``.

    Args:
        part_instance:
        copy_dict:
    """
    part = part_instance.reference()
    if use_undostack:
        undostack = part.undoStack()
        undostack.beginMacro("Import to Part")
    id_num_offset = part.getMaxIdNum() + 1
    print("Starting from", id_num_offset)
    vh_id_list = copy_dict['vh_list']
    origins = copy_dict['origins']
    vh_props = copy_dict['virtual_helices']
    name_suffix = ".%d"

    keys = list(vh_props.keys())
    name_index = keys.index('name')
    new_vh_id_set = set()
    copied_vh_index_set = set()
    if offset is None:
        offx, offy = 0, 0
    else:
        offx, offy = offset

    for i, pair in enumerate(vh_id_list):
        id_num, size = pair
        x, y = origins[i]
        if offset is not None:
            x += offx
            y += offy
        try:
            # Don't use id_num since is compacted
            z = vh_props['z'][i]
        except:
            print(vh_props)
            raise
        vals = [vh_props[k][i] for k in keys]
        new_id_num = i + id_num_offset
        # print("creating", new_id_num)
        vals[name_index] += (name_suffix % new_id_num)
        did_create = part.createVirtualHelix(x, y, z, size,
                                id_num=new_id_num,
                                properties=(keys, vals),
                                safe=use_undostack,
                                use_undostack=use_undostack)
        if did_create:
            copied_vh_index_set.add(i)
            new_vh_id_set.add(new_id_num)
    # end for
    strands = copy_dict['strands']
    strand_index_list = strands['indices']
    color_list = strands['properties']
    for i, idx_set in enumerate(strand_index_list):
        if i not in copied_vh_index_set:
            continue
        if idx_set is not None:
            # print("getting", new_id_num)
            fwd_strand_set, rev_strand_set = part.getStrandSets(i + id_num_offset)
            fwd_idxs, rev_idxs = idx_set
            fwd_colors, rev_colors = color_list[i]
            for idxs, color in zip(fwd_idxs, fwd_colors):
                low_idx, high_idx = idxs
                fwd_strand_set.createDeserializedStrand(low_idx, high_idx, color,
                                                        use_undostack=use_undostack)

            for idxs, color in zip(rev_idxs, rev_colors):
                low_idx, high_idx = idxs
                rev_strand_set.createDeserializedStrand(low_idx, high_idx, color,
                                                        use_undostack=use_undostack)
    # end def

    xovers = copy_dict['xovers']
    for from_i, from_is_fwd, from_idx, to_i, to_is_fwd, to_idx in xovers:
        from_strand = part.getStrand(from_is_fwd, from_i + id_num_offset, from_idx)
        to_strand = part.getStrand(to_is_fwd, to_i + id_num_offset, to_idx)
        part.createXover(from_strand, from_idx,
                         to_strand, to_idx,
                         update_oligo=use_undostack,
                         use_undostack=use_undostack)
    if not use_undostack:
        RefreshOligosCommand(part).redo()

    # INSERTIONS, SKIPS
    for i, idx, length in copy_dict['insertions']:
        fwd_strand = part.getStrand(True, i + id_num_offset, idx)
        rev_strand = part.getStrand(False, i + id_num_offset, idx)
        if fwd_strand:
            fwd_strand.addInsertion(idx, length, use_undostack=use_undostack)
        elif rev_strand:
            rev_strand.addInsertion(idx, length, use_undostack=use_undostack)
        else:
            ins = 'Insertion' if length > 0 else 'Skip'
            err = "Cannot find strand for {} at {}[{}]"
            print(err.format(ins, i + id_num_offset, idx))

    """
    TODO: figure out copy_dict['view_properties'] handling here
    """
    if use_undostack:
        undostack.endMacro()
    return new_vh_id_set
# end def
